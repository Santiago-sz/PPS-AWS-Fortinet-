"""Arranque opcional de la API local como proceso hijo de la aplicación.

La aplicación sigue sin credenciales de AWS: solo inicia el servidor local con
el mismo intérprete y lo termina al salir. Si algo ya responde en el puerto, no
se inicia un segundo servidor ni se detiene el existente.
"""

import importlib.util
from pathlib import Path
import socket
import subprocess
import sys

PORT = 8765
DEFAULT_URL = f"http://127.0.0.1:{PORT}"
# Código de salida de la API cuando rechaza sus argumentos; con --aws-bridge
# indica que falta la configuración de AWS.
CONFIGURATION_ERROR = 2


def port_answers(port=PORT, timeout=0.25):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def repository_root():
    """Raíz del repositorio cuando la aplicación se ejecuta desde un checkout."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "local-api" / "launch.py").is_file() else None


def api_command(bridge, root=None):
    """Comando para iniciar la API con este mismo intérprete, o None si no es posible."""
    if getattr(sys, "frozen", False):
        return None
    if importlib.util.find_spec("pps_api") is not None:
        command = [sys.executable, "-m", "pps_api"]
    elif root is not None and (Path(root) / "local-api" / "launch.py").is_file():
        command = [sys.executable, str(Path(root) / "local-api" / "launch.py")]
    else:
        return None
    command += ["serve", "--port", str(PORT)]
    return command + ["--aws-bridge"] if bridge else command


class LocalApiProcess:
    """Estados: idle, external, starting, running, unavailable, failed."""

    def __init__(
        self, popen=subprocess.Popen, probe=port_answers, command=None, cwd=None, log_path=None
    ):
        root = repository_root()
        self.popen, self.probe = popen, probe
        self.command = command or (lambda bridge: api_command(bridge, root))
        # Desde la raíz, la API encuentra el mismo .env y la misma base que por consola.
        self.cwd = str(cwd or root) if (cwd or root) else None
        self.log_path = Path(log_path) if log_path else None
        self.process, self.log_file = None, None
        self.state, self.bridge = "idle", False

    def ensure_started(self):
        if self.process is not None and self.process.poll() is None:
            return self.state
        if self.probe():
            self.state = "external"
            return self.state
        return self._spawn(bridge=True)

    def _spawn(self, bridge):
        command = self.command(bridge)
        if not command:
            self.state = "unavailable"
            return self.state
        self._close_log()
        output = subprocess.DEVNULL
        try:
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                output = self.log_file = open(self.log_path, "wb")
            self.process = self.popen(
                command,
                cwd=self.cwd,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.process = None
            self._close_log()
            self.state = "failed"
            return self.state
        self.bridge, self.state = bridge, "starting"
        return self.state

    def poll(self):
        """Avanza el estado de un inicio en curso; no bloquea."""
        if self.state != "starting":
            return self.state
        code = self.process.poll()
        if code is not None:
            self.process = None
            if code == CONFIGURATION_ERROR and self.bridge:
                # Sin configuración de AWS la API sigue siendo útil, sin envío automático.
                return self._spawn(bridge=False)
            self._close_log()
            self.state = "failed"
        elif self.probe():
            self.state = "running"
        return self.state

    def stop(self):
        """Termina el proceso que inició la aplicación; nunca uno ajeno."""
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._close_log()
        self.state = "idle"

    def _close_log(self):
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None
