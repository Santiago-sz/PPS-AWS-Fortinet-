"""Ciclo opcional de envío y recuperación; se activa solo con `serve --aws-bridge`.

Repite las dos operaciones explícitas del puente (`dispatch` y `sync`) sin
cambiar sus reglas: un envío ambiguo no se repite y un conflicto por ejecuciones
duplicadas no se resuelve solo. Un fallo de AWS o de red no detiene el servidor.
"""

import sys
import threading
from pathlib import Path

MIN_INTERVAL = 5.0
DEFAULT_INTERVAL = 15.0

STEPS = (("dispatch", "envío", "enviadas"), ("sync", "recuperación", "con reporte recuperado"))


def describe(exc):
    """Tipo del error y código de AWS; nunca el mensaje, que puede incluir datos del entorno."""
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    code = code or getattr(exc, "code", None)
    name = type(exc).__name__
    return f"{name}: {code}" if isinstance(code, str) and code.isidentifier() else name


def log_to_stderr(message):
    print(message, file=sys.stderr, flush=True)


class BridgeWorker:
    def __init__(self, bridge, interval=DEFAULT_INTERVAL, log=log_to_stderr):
        self.bridge, self.interval, self.log = bridge, float(interval), log
        self._stop = threading.Event()
        self._thread = None
        self._last_error = {}

    def tick(self):
        """Un ciclo: enviar lo pendiente y después recuperar reportes."""
        for method, label, done in STEPS:
            try:
                count = getattr(self.bridge, method)()
            except Exception as exc:
                error = describe(exc)
                # Un error repetido en cada ciclo se informa una sola vez.
                if self._last_error.get(method) != error:
                    self._last_error[method] = error
                    self.log(f"Puente AWS: falló el paso de {label} ({error}). El ciclo continúa.")
                continue
            if self._last_error.pop(method, None):
                self.log(f"Puente AWS: el paso de {label} volvió a funcionar.")
            if count:
                self.log(f"Puente AWS: auditorías {done}: {count}.")

    def _run(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pps-aws-bridge", daemon=True)
        self._thread.start()

    def stop(self, timeout=10.0):
        """Pide el fin del ciclo y espera el paso en curso hasta `timeout` segundos."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)


def build_bridge_worker(service, env_file, interval=DEFAULT_INTERVAL):
    """Valida la configuración y arma el ciclo, sin iniciarlo ni contactar AWS.

    Lanza ValueError con un mensaje para el operador si falta configuración.
    """
    if not isinstance(interval, (int, float)) or interval < MIN_INTERVAL:
        raise ValueError(f"El intervalo del puente AWS debe ser de {MIN_INTERVAL:g} s o más.")
    env_file = Path(env_file)
    if env_file != Path(".env") and not env_file.is_file():
        raise ValueError("No existe el archivo indicado en --env-file.")

    from .config import aws_options, load_settings

    options, policies, reports = aws_options(load_settings(env_file))

    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError

    from .bridge import Bridge

    try:
        session = boto3.Session(**options)
        credentials = session.get_credentials()
    except BotoCoreError as exc:
        raise ValueError(
            f"La configuración de AWS no es válida ({type(exc).__name__}). "
            "Revisá el perfil o las claves en .env."
        ) from None
    if credentials is None:
        raise ValueError(
            "No se encontraron credenciales de AWS. Completá AWS_PROFILE o las claves en .env."
        )
    # Igual que en los comandos explícitos: un reintento del SDK podría duplicar un envío.
    s3 = session.client("s3", config=Config(retries={"total_max_attempts": 1}))
    return BridgeWorker(Bridge(service, s3, policies, reports), interval)
