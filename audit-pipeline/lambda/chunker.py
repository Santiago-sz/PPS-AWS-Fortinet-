"""
Chunking de normativas extraídas, preservando límites de cláusula/sección.

Contrato: chunk(text, metadata) -> Chunk[] (ver design.md, interfaces):
  Chunk = {"chunk_id","ordinal","heading_path":[...],"page","char_span","text"}

Estrategia de detección de límites de cláusula:
  - Si `metadata` trae headings reales (viene de un DOCX, ver extractor.py:
    estilos "Heading N") se usan esos límites tal cual, con su nivel.
  - Si no (viene de un PDF, sin estilos), se detectan límites por regex
    sobre líneas que empiezan con "Capítulo N" / "Sección N" / "Artículo N"
    o con numeración jerárquica ("1.2.3 ...").

Cada bloque de cláusula conserva su `heading_path` (pila de headings
activos por nivel) y su página de origen (solo disponible para PDF).
Los bloques se agrupan en Chunks respetando un presupuesto de caracteres
por chunk (`max_chunk_chars`) SIN mezclar cláusulas con heading_path
distinto — así cada chunk retiene una referencia inequívoca a su
cláusula/sección de origen. Un bloque que por sí solo excede el
presupuesto se divide en sub-chunks (mismo heading_path, cortados en
espacios) en vez de mezclarse con otras cláusulas.

`retrieve_relevant` es el helper de retrieval léxico (TF-IDF, sin
dependencias externas) usado cuando la lista de PolicyCheck del reduce
desborda su propio presupuesto de prompt (ver design.md, Decisión #3).
Si ningún chunk es relevante para la query, reporta explícitamente
"no relevant chunks found" en vez de dejar pasar un contexto vacío en
silencio (spec: Requirement "Traceable Chunking for Long Policies").
"""

import math
import re
from collections import Counter

DEFAULT_MAX_CHUNK_CHARS = 4000

_CLAUSE_LINE_RE = re.compile(r"(?im)^((?:Cap[ií]tulo|Secci[oó]n|Art[ií]culo)\s+[IVXLCDM0-9]+.*)$")
_NUMERIC_LINE_RE = re.compile(r"(?m)^(\d+(?:\.\d+)*)\.?\s+\S.*$")

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")

NO_RELEVANT_CHUNKS_MESSAGE = "no relevant chunks found"


class NoRelevantChunksError(Exception):
    """Ninguna cláusula/sección indexada es relevante para la query dada.

    Se levanta en vez de devolver una lista vacía silenciosamente — el
    caller (llm_client.py, fuera de alcance en esta fase) debe manejar
    este caso explícitamente, no tratarlo como "sin contexto adicional".
    """


def _keyword_level(first_word: str) -> int:
    word = first_word.lower()
    if word.startswith("cap"):
        return 1
    if word.startswith("secc") or word.startswith("sección"):
        return 2
    return 3  # articulo/artículo


def _detect_boundaries_from_text(text: str) -> list[tuple[int, int, str]]:
    boundaries: list[tuple[int, int, str]] = []
    claimed_starts: set[int] = set()

    for m in _CLAUSE_LINE_RE.finditer(text):
        title = m.group(1).strip()
        level = _keyword_level(title.split()[0])
        start = m.start(1)
        boundaries.append((start, level, title))
        claimed_starts.add(start)

    for m in _NUMERIC_LINE_RE.finditer(text):
        start = m.start(1)
        if start in claimed_starts:
            continue
        numeric_prefix = m.group(1)
        level = numeric_prefix.count(".") + 1
        title = m.group(0).strip()
        boundaries.append((start, level, title))

    return boundaries


def _detect_boundaries_from_metadata(metadata: list[dict]) -> list[tuple[int, int, str]]:
    return [
        (m["char_start"], m["level"], m["heading"])
        for m in metadata
        if m.get("heading") is not None
    ]


def _build_clause_blocks(text: str, metadata: list[dict]) -> list[dict]:
    has_structural_headings = any(m.get("heading") is not None for m in metadata)

    if has_structural_headings:
        boundaries = _detect_boundaries_from_metadata(metadata)
    else:
        boundaries = _detect_boundaries_from_text(text)

    boundaries.sort(key=lambda b: b[0])

    deduped: list[tuple[int, int, str]] = []
    seen_starts: set[int] = set()
    for start, level, title in boundaries:
        if start in seen_starts:
            continue
        seen_starts.add(start)
        deduped.append((start, level, title))
    boundaries = deduped

    events: list[tuple[int, int | None, str | None]] = []
    if not boundaries or boundaries[0][0] > 0:
        events.append((0, None, None))
    events.extend(boundaries)

    stack: list[tuple[int, str]] = []
    raw_blocks: list[dict] = []
    for start, level, title in events:
        if level is not None:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        raw_blocks.append({"start": start, "heading_path": [t for _, t in stack]})

    for i, block in enumerate(raw_blocks):
        block["end"] = raw_blocks[i + 1]["start"] if i + 1 < len(raw_blocks) else len(text)

    return [b for b in raw_blocks if b["end"] > b["start"]]


def _page_for_position(position: int, metadata: list[dict]) -> int | None:
    for m in metadata:
        if m.get("page") is not None and m["char_start"] <= position < m["char_end"]:
            return m["page"]
    return None


def _split_span_by_budget(text: str, start: int, end: int, max_len: int) -> list[tuple[int, int]]:
    """Divide [start, end) en sub-spans <= max_len, cortando en espacios
    cuando es posible para no partir palabras a la mitad."""
    spans: list[tuple[int, int]] = []
    pos = start
    while end - pos > max_len:
        cut = text.rfind(" ", pos, pos + max_len)
        if cut <= pos:
            cut = pos + max_len
        spans.append((pos, cut))
        new_pos = cut
        while new_pos < end and text[new_pos] == " ":
            new_pos += 1
        pos = new_pos
    if pos < end:
        spans.append((pos, end))
    return spans


def _common_prefix(a: list[str], b: list[str]) -> list[str]:
    prefix = []
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        prefix.append(x)
    return prefix


def chunk(
    text: str,
    metadata: list[dict],
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    group_by_budget: bool = True,
) -> list[dict]:
    """Divide `text` en Chunks preservando límites de cláusula/sección.

    Un bloque que excede `max_chunk_chars` por sí solo SIEMPRE se divide
    en varios chunks consecutivos que comparten su heading_path original
    (nunca se mezcla con otra cláusula).

    Si `group_by_budget` es True (default), cláusulas hermanas chicas y
    consecutivas que comparten un ancestro en su heading_path se agrupan
    en un mismo chunk mientras no se exceda `max_chunk_chars` — evita que
    normativas con muchas sub-cláusulas cortas (ej. "1.1", "1.2", ...)
    generen un chunk por cada una. El heading_path del chunk agrupado
    queda como el prefijo común (ancestro compartido) de las cláusulas
    que agrupa; la cita exacta de cada sub-cláusula sigue siendo
    recuperable via `char_span`. Con `group_by_budget=False` cada bloque
    de cláusula se emite como su propio chunk (útil quirúrgicamente para
    inspeccionar los límites de cláusula detectados sin la agrupación).
    """
    blocks = _build_clause_blocks(text, metadata)
    chunks: list[dict] = []
    ordinal = 0

    def emit(start: int, end: int, heading_path: list[str]) -> None:
        nonlocal ordinal
        ordinal += 1
        chunks.append(
            {
                "chunk_id": f"chunk-{ordinal:04d}",
                "ordinal": ordinal,
                "heading_path": heading_path,
                "page": _page_for_position(start, metadata),
                "char_span": [start, end],
                "text": text[start:end],
            }
        )

    group: dict | None = None  # {"start", "end", "heading_path"}

    def flush_group() -> None:
        nonlocal group
        if group is not None:
            emit(group["start"], group["end"], group["heading_path"])
            group = None

    for block in blocks:
        block_len = block["end"] - block["start"]

        if block_len > max_chunk_chars:
            flush_group()
            for span_start, span_end in _split_span_by_budget(
                text, block["start"], block["end"], max_chunk_chars
            ):
                emit(span_start, span_end, block["heading_path"])
            continue

        if not group_by_budget:
            emit(block["start"], block["end"], block["heading_path"])
            continue

        merge_prefix = (
            _common_prefix(group["heading_path"], block["heading_path"])
            if group is not None
            else []
        )
        same_group = (
            group is not None
            and merge_prefix
            and (block["end"] - group["start"]) <= max_chunk_chars
        )

        if same_group:
            group["end"] = block["end"]
            group["heading_path"] = merge_prefix
        else:
            flush_group()
            group = {
                "start": block["start"],
                "end": block["end"],
                "heading_path": block["heading_path"],
            }

    flush_group()
    return chunks


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _term_frequencies(tokens: list[str]) -> dict[str, float]:
    counts = Counter(tokens)
    total = sum(counts.values()) or 1
    return {term: count / total for term, count in counts.items()}


def _inverse_document_frequencies(documents_tokens: list[list[str]]) -> dict[str, float]:
    n_docs = len(documents_tokens)
    document_frequency: Counter = Counter()
    for tokens in documents_tokens:
        for term in set(tokens):
            document_frequency[term] += 1
    return {
        term: math.log((n_docs + 1) / (count + 1)) + 1 for term, count in document_frequency.items()
    }


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = _term_frequencies(tokens)
    return {term: weight * idf.get(term, 0.0) for term, weight in tf.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    common_terms = set(vec_a) & set(vec_b)
    dot_product = sum(vec_a[t] * vec_b[t] for t in common_terms)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def retrieve_relevant(chunks: list[dict], query: str, top_k: int = 5) -> list[dict]:
    """Retrieval léxico TF-IDF sobre `chunks` para `query`.

    Levanta NoRelevantChunksError si ningún chunk tiene similitud > 0
    con la query (ningún término en común) — nunca devuelve una lista
    vacía en silencio.
    """
    if not chunks:
        raise NoRelevantChunksError(NO_RELEVANT_CHUNKS_MESSAGE)

    documents_tokens = [_tokenize(c["text"]) for c in chunks]
    idf = _inverse_document_frequencies(documents_tokens)
    query_vector = _tfidf_vector(_tokenize(query), idf)

    scored: list[tuple[float, dict]] = []
    for chunk_obj, tokens in zip(chunks, documents_tokens, strict=False):
        score = _cosine_similarity(query_vector, _tfidf_vector(tokens, idf))
        if score > 0.0:
            scored.append((score, chunk_obj))

    if not scored:
        raise NoRelevantChunksError(NO_RELEVANT_CHUNKS_MESSAGE)

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk_obj for _, chunk_obj in scored[:top_k]]
