"""
Tests para chunker.py.

Todo el módulo es puro (texto + metadata -> Chunk[], o Chunk[] + query ->
Chunk[] relevantes) — sin I/O, sin mocks.
"""

import pytest

from chunker import (
    NO_RELEVANT_CHUNKS_MESSAGE,
    NoRelevantChunksError,
    chunk,
    retrieve_relevant,
)


def _pdf_style_metadata(page_spans: list[tuple[int, int, int]]) -> list[dict]:
    """page_spans: lista de (page_number, char_start, char_end)."""
    return [
        {"page": page, "heading": None, "level": None, "char_start": start, "char_end": end}
        for page, start, end in page_spans
    ]


class TestChunkClauseBoundaries:
    def test_pdf_style_text_is_split_on_articulo_boundaries(self):
        text = (
            "Articulo 1. Objetivo\n"
            "Este articulo define el objetivo general de la politica.\n"
            "Articulo 2. Alcance\n"
            "Este articulo define el alcance de aplicacion.\n"
        )
        metadata = _pdf_style_metadata([(1, 0, len(text))])

        chunks = chunk(text, metadata)

        assert len(chunks) == 2
        assert chunks[0]["heading_path"] == ["Articulo 1. Objetivo"]
        assert chunks[1]["heading_path"] == ["Articulo 2. Alcance"]
        assert "objetivo general" in chunks[0]["text"]
        assert "alcance de aplicacion" in chunks[1]["text"]

    def test_docx_style_text_uses_heading_metadata_not_regex(self):
        text = (
            "Politica de Seguridad\n"
            "Texto introductorio.\n"
            "Articulo 1. Objetivo\n"
            "Contenido del articulo 1.\n"
            "Articulo 2. Alcance\n"
            "Contenido del articulo 2.\n"
        )
        # char offsets calculados a mano sobre `text` (incluye el \n final de cada linea)
        idx_intro_heading = text.index("Politica de Seguridad")
        idx_art1 = text.index("Articulo 1. Objetivo")
        idx_art2 = text.index("Articulo 2. Alcance")
        metadata = [
            {
                "page": None,
                "heading": "Politica de Seguridad",
                "level": 1,
                "char_start": idx_intro_heading,
                "char_end": idx_intro_heading + len("Politica de Seguridad"),
            },
            {
                "page": None,
                "heading": "Articulo 1. Objetivo",
                "level": 2,
                "char_start": idx_art1,
                "char_end": idx_art1 + len("Articulo 1. Objetivo"),
            },
            {
                "page": None,
                "heading": "Articulo 2. Alcance",
                "level": 2,
                "char_start": idx_art2,
                "char_end": idx_art2 + len("Articulo 2. Alcance"),
            },
        ]

        # group_by_budget=False aisla la deteccion de limites via metadata
        # de la logica de agrupacion (cubierta aparte en TestChunkPromptBudget).
        chunks = chunk(text, metadata, group_by_budget=False)

        assert len(chunks) == 3
        assert chunks[0]["heading_path"] == ["Politica de Seguridad"]
        assert chunks[1]["heading_path"] == ["Politica de Seguridad", "Articulo 1. Objetivo"]
        assert chunks[2]["heading_path"] == ["Politica de Seguridad", "Articulo 2. Alcance"]

    def test_numeric_clause_numbering_is_detected_and_nested(self):
        text = (
            "1. Introduccion\n"
            "Texto de introduccion.\n"
            "1.1 Definiciones\n"
            "Texto de definiciones.\n"
            "2. Alcance\n"
            "Texto de alcance.\n"
        )
        metadata = _pdf_style_metadata([(1, 0, len(text))])

        # group_by_budget=False aisla la deteccion/anidado de limites de
        # clausula de la logica de agrupacion por presupuesto (cubierta
        # aparte en TestChunkPromptBudget) — cada bloque queda en su
        # propio chunk para poder verificar el heading_path exacto.
        chunks = chunk(text, metadata, group_by_budget=False)

        assert [c["heading_path"] for c in chunks] == [
            ["1. Introduccion"],
            ["1. Introduccion", "1.1 Definiciones"],
            ["2. Alcance"],
        ]

    def test_text_with_no_clause_markers_becomes_a_single_chunk(self):
        text = "Texto plano sin ninguna marca de clausula ni articulo."
        metadata = _pdf_style_metadata([(1, 0, len(text))])

        chunks = chunk(text, metadata)

        assert len(chunks) == 1
        assert chunks[0]["heading_path"] == []
        assert chunks[0]["text"] == text


class TestChunkPageTracking:
    def test_chunk_page_matches_the_page_metadata_span_it_falls_into(self):
        page1_text = "Articulo 1. Objetivo\nContenido de la pagina uno.\n"
        page2_text = "Articulo 2. Alcance\nContenido de la pagina dos.\n"
        text = page1_text + page2_text
        metadata = _pdf_style_metadata([(1, 0, len(page1_text)), (2, len(page1_text), len(text))])

        chunks = chunk(text, metadata)

        assert chunks[0]["page"] == 1
        assert chunks[1]["page"] == 2


class TestChunkPromptBudget:
    def test_small_consecutive_clauses_under_same_heading_are_grouped(self):
        text = (
            "Capitulo I. Disposiciones Generales\n"
            "1.1 Primer punto breve.\n"
            "1.2 Segundo punto breve.\n"
            "Capitulo II. Otro Capitulo\n"
            "2.1 Contenido del segundo capitulo.\n"
        )
        metadata = _pdf_style_metadata([(1, 0, len(text))])

        chunks = chunk(text, metadata, max_chunk_chars=4000)

        # Los dos incisos bajo "Capitulo I" caben holgadamente en el
        # presupuesto y comparten heading_path -> se agrupan en un chunk.
        capitulo_i_chunks = [
            c for c in chunks if c["heading_path"][0] == "Capitulo I. Disposiciones Generales"
        ]
        assert len(capitulo_i_chunks) == 1
        assert "Primer punto breve" in capitulo_i_chunks[0]["text"]
        assert "Segundo punto breve" in capitulo_i_chunks[0]["text"]

    def test_oversized_single_clause_is_split_without_mixing_other_clauses(self):
        huge_body = "Texto de cumplimiento normativo repetido. " * 200  # ~8600 chars
        text = f"Articulo 1. Objetivo\n{huge_body}\nArticulo 2. Alcance\nContenido breve.\n"
        metadata = _pdf_style_metadata([(1, 0, len(text))])

        chunks = chunk(text, metadata, max_chunk_chars=4000)

        art1_chunks = [c for c in chunks if c["heading_path"] == ["Articulo 1. Objetivo"]]
        art2_chunks = [c for c in chunks if c["heading_path"] == ["Articulo 2. Alcance"]]

        assert len(art1_chunks) >= 2  # el articulo 1 solo no entra en un chunk
        for c in art1_chunks:
            assert len(c["text"]) <= 4000
            assert "Contenido breve" not in c["text"]  # no se mezcla con el articulo 2
        assert len(art2_chunks) == 1
        assert "Contenido breve" in art2_chunks[0]["text"]

    def test_reassembling_char_spans_reproduces_original_text_slice(self):
        text = "Articulo 1. Objetivo\nPrimer parrafo.\nArticulo 2. Alcance\nSegundo parrafo.\n"
        metadata = _pdf_style_metadata([(1, 0, len(text))])

        chunks = chunk(text, metadata)

        for c in chunks:
            start, end = c["char_span"]
            assert text[start:end] == c["text"]


class TestChunkIdsAndOrdinals:
    def test_ordinals_and_chunk_ids_are_sequential(self):
        text = "Articulo 1. Uno\nA.\nArticulo 2. Dos\nB.\nArticulo 3. Tres\nC.\n"
        metadata = _pdf_style_metadata([(1, 0, len(text))])

        chunks = chunk(text, metadata)

        assert [c["ordinal"] for c in chunks] == [1, 2, 3]
        assert [c["chunk_id"] for c in chunks] == ["chunk-0001", "chunk-0002", "chunk-0003"]


class TestRetrieveRelevant:
    def _make_chunks(self, texts: list[str]) -> list[dict]:
        return [
            {
                "chunk_id": f"chunk-{i:04d}",
                "ordinal": i,
                "heading_path": [f"Articulo {i}"],
                "page": 1,
                "char_span": [0, len(t)],
                "text": t,
            }
            for i, t in enumerate(texts, start=1)
        ]

    def test_returns_chunks_ranked_by_relevance_to_query(self):
        chunks = self._make_chunks(
            [
                "Politica de contraseñas y autenticacion multifactor obligatoria.",
                "Politica de respaldo de datos y retencion de backups.",
                "Firewall y reglas de filtrado de trafico de red perimetral.",
            ]
        )

        results = retrieve_relevant(chunks, query="autenticacion multifactor contraseñas", top_k=2)

        assert len(results) >= 1
        assert results[0]["text"] == chunks[0]["text"]

    def test_no_matching_chunks_raises_explicit_error(self):
        chunks = self._make_chunks(
            [
                "Politica de contraseñas y autenticacion multifactor.",
                "Politica de respaldo de datos y retencion de backups.",
            ]
        )

        with pytest.raises(NoRelevantChunksError) as exc_info:
            retrieve_relevant(chunks, query="xenozorb quantumflux nonexistentterm")

        assert str(exc_info.value) == NO_RELEVANT_CHUNKS_MESSAGE

    def test_empty_chunk_list_raises_explicit_error(self):
        with pytest.raises(NoRelevantChunksError):
            retrieve_relevant([], query="cualquier cosa")
