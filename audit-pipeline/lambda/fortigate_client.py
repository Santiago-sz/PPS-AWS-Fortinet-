"""
FortiGate REST API client.

Hace todas las llamadas HTTP al FortiGate y devuelve la data cruda.
Separa la responsabilidad de "obtener datos" del resto del sistema —
si cambia la API de FortiGate, solo se toca este archivo.
"""

import json
import logging
import ssl
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


# Endpoints a consultar y su etiqueta en el reporte final.
# Formato: (path en la API, clave en el dict de resultados)
ENDPOINTS = [
    ("system/global", "system_global"),
    ("system/interface", "interfaces"),
    ("system/admin", "admins"),
    ("system/dns", "dns"),
    ("firewall/policy", "firewall_policies"),
    ("vpn.ipsec/phase1-interface", "vpn_ipsec"),
    ("vpn.ssl/settings", "vpn_ssl"),
    ("user/local", "local_users"),
    ("ips/sensor", "ips_sensors"),
    ("antivirus/profile", "av_profiles"),
    ("webfilter/profile", "webfilter_profiles"),
]


class FortiGateClient:
    """
    Cliente HTTP para la REST API de FortiGate (v2).

    Usa urllib en lugar de requests para no requerir dependencias externas
    en Lambda — el runtime Python 3.x ya incluye urllib en la stdlib.
    """

    def __init__(self, host: str, token: str, verify_ssl: bool = True):
        """
        Args:
            host:       IP o hostname del FortiGate, sin protocolo ni slash final.
                        Ej: "192.168.1.1"
            token:      API token generado en el FortiGate (System > API Users).
            verify_ssl: False solo en labs con certificado self-signed.
                        En producción siempre True.
        """
        self.base_url = f"https://{host}/api/v2/cmdb"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # Si verify_ssl=False, creamos un contexto que ignora el certificado.
        # Útil en labs, pero nunca en producción.
        if verify_ssl:
            self.ssl_context = ssl.create_default_context()
        else:
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def _get(self, path: str) -> dict | list | None:
        """
        Hace un GET a un endpoint de la API y devuelve el campo 'results'.

        La API de FortiGate siempre responde con:
        {
            "http_status": 200,
            "results": [...],
            ...
        }
        Devolvemos solo 'results' para simplificar el consumo.
        """
        url = f"{self.base_url}/{path}"
        req = urllib.request.Request(url, headers=self.headers)

        try:
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("results")

        except urllib.error.HTTPError as e:
            # 401 = token inválido o expirado
            # 403 = el usuario de API no tiene permiso para este recurso
            logger.warning("HTTP %s al consultar %s: %s", e.code, path, e.reason)
            return None

        except urllib.error.URLError as e:
            # El FortiGate no es alcanzable desde la Lambda — revisar SG o VPN
            logger.error("No se puede conectar al FortiGate (%s): %s", url, e.reason)
            return None

        except Exception as e:
            logger.error("Error inesperado consultando %s: %s", path, str(e))
            return None

    def collect_all(self) -> dict:
        """
        Consulta todos los endpoints definidos en ENDPOINTS.

        Devuelve un dict con la data de cada sección.
        Si un endpoint falla, lo registra como None en lugar de abortar todo
        — el análisis continúa con la data parcial disponible.
        """
        logger.info("Iniciando recolección de datos del FortiGate")
        data = {}

        for path, key in ENDPOINTS:
            logger.info("Consultando: %s", path)
            result = self._get(path)

            if result is None:
                logger.warning("Sin datos para %s — se analizará como vacío", key)

            data[key] = result

        populated = sum(1 for v in data.values() if v is not None)
        logger.info("Recolección completa: %d/%d endpoints con datos", populated, len(ENDPOINTS))

        return data
