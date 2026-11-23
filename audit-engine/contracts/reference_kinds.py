"""
Tipo de un documento de referencia: técnico o normativo.

La base de conocimientos guarda en un mismo bucket normativas (NIST, STIG,
normativa nacional) y documentación técnica: notas propias del laboratorio
bajo `propio/` y documentación del fabricante bajo `fortinet/`. Las dos sirven
de consulta al generar un control, pero solo las primeras son normativa. Este
módulo fija la regla en un único lugar para que el generador (bloque
`knowledge_base` del manifest) y el reporte usen la misma.

La regla mira solo la clave del objeto, que es lo único que viaja del origen
de un fragmento (decisión 11). No consulta ningún servicio y no cambia qué se
recupera ni qué llega al prompt. Agregar una carpeta técnica nueva al bucket
exige agregar su prefijo acá; mientras tanto se informa como normativa.
"""

TECHNICAL = "technical"
NORMATIVE = "normative"

# Prefijos de clave cuyos documentos son técnicos. Todo lo demás, incluido un
# origen ausente, se informa como normativo.
TECHNICAL_PREFIXES = ("propio/", "fortinet/")


def classify(source) -> str:
    """`TECHNICAL` si la clave empieza con un prefijo técnico; si no,
    `NORMATIVE`. Tolera una barra inicial, espacios y mayúsculas."""
    if not isinstance(source, str):
        return NORMATIVE
    key = source.strip().lstrip("/").lower()
    return TECHNICAL if key.startswith(TECHNICAL_PREFIXES) else NORMATIVE
