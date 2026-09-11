"""
Extracción de texto de normativas subidas en PDF/DOCX.

Contrato: extract(bytes, content_type) -> (text, metadata).

Reglas duras (ver specs/policy-ingestion/spec.md):
  - Nunca se trunca el texto extraído — el patrón MAX_DATA_CHARS de
    analyzer.py NO se reutiliza acá.
  - Documento corrupto, encriptado o sin capa de texto extraíble
    (ej. PDF escaneado) -> falla explícita (ExtractionError), nunca un
    resultado parcial o vacío tratado como éxito.

`metadata` es una lista de elementos con esta forma:
  {"page": int|None, "heading": str|None, "level": int|None,
   "char_start": int, "char_end": int}

Para PDF: un elemento por página (heading/level siempre None — pypdf no
expone estilos, solo contenido). Para DOCX: un elemento por párrafo
(page siempre None — DOCX no tiene concepto de página sin renderizar;
heading/level se completan cuando el párrafo usa un estilo "Heading N").
chunker.py combina ambas señales para reconstruir clause/heading_path.
"""

import io
import logging
import zipfile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader

logger = logging.getLogger(__name__)

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ExtractionError(Exception):
    """Falla explícita de extracción.

    `reason` es una de: "corrupt", "encrypted", "no_text_layer",
    "unsupported_content_type" — para que el caller (handler_generator.py,
    fuera de alcance en esta fase) pueda escribir un reporte de fallo
    específico en vez de un error genérico.
    """

    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(message)


def _extract_pdf(data: bytes) -> tuple[str, list[dict]]:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        raise ExtractionError("corrupt", f"No se pudo leer el PDF: {e}") from e

    if reader.is_encrypted:
        raise ExtractionError(
            "encrypted",
            "El PDF está encriptado; no se puede extraer texto sin contraseña.",
        )

    text_parts: list[str] = []
    metadata: list[dict] = []
    cursor = 0

    try:
        pages = reader.pages
        for i, page in enumerate(pages):
            page_text = page.extract_text() or ""
            start = cursor
            text_parts.append(page_text)
            cursor += len(page_text)
            metadata.append(
                {
                    "page": i + 1,
                    "heading": None,
                    "level": None,
                    "char_start": start,
                    "char_end": cursor,
                }
            )
            text_parts.append("\n")
            cursor += 1
    except Exception as e:
        raise ExtractionError("corrupt", f"Error al extraer texto del PDF: {e}") from e

    full_text = "".join(text_parts)
    if not full_text.strip():
        raise ExtractionError(
            "no_text_layer",
            "El PDF no tiene una capa de texto extraíble (posible escaneo de imagen).",
        )

    return full_text, metadata


def _heading_level(style_name: str) -> int | None:
    """'Heading 2' -> 2. Devuelve None si el estilo no es un heading."""
    if not style_name or not style_name.lower().startswith("heading"):
        return None
    digits = "".join(ch for ch in style_name if ch.isdigit())
    return int(digits) if digits else 1


def _extract_docx(data: bytes) -> tuple[str, list[dict]]:
    try:
        document = Document(io.BytesIO(data))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as e:
        raise ExtractionError("corrupt", f"No se pudo leer el DOCX: {e}") from e

    text_parts: list[str] = []
    metadata: list[dict] = []
    cursor = 0

    for para in document.paragraphs:
        para_text = para.text
        style_name = para.style.name if para.style is not None else ""
        level = _heading_level(style_name)
        heading = para_text if level is not None else None

        start = cursor
        text_parts.append(para_text)
        cursor += len(para_text)
        metadata.append(
            {
                "page": None,
                "heading": heading,
                "level": level,
                "char_start": start,
                "char_end": cursor,
            }
        )
        text_parts.append("\n")
        cursor += 1

    full_text = "".join(text_parts)
    if not full_text.strip():
        raise ExtractionError("no_text_layer", "El DOCX no contiene texto extraíble.")

    return full_text, metadata


def extract(data: bytes, content_type: str) -> tuple[str, list[dict]]:
    """Extrae texto completo + metadata de página/heading de un PDF o DOCX.

    Nunca trunca. Ante corrupción, encriptación o ausencia de capa de
    texto, levanta ExtractionError en vez de devolver un resultado parcial.
    """
    logger.info("Extrayendo documento — content_type=%s, %d bytes", content_type, len(data))

    if content_type == PDF_CONTENT_TYPE:
        return _extract_pdf(data)
    if content_type == DOCX_CONTENT_TYPE:
        return _extract_docx(data)

    raise ExtractionError(
        "unsupported_content_type",
        f"Tipo de contenido no soportado para extracción: {content_type!r}",
    )
