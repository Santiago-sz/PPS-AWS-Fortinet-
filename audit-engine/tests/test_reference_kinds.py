"""
Tests para reference_kinds.py: clasificación de un documento de referencia en
técnico o normativo según el prefijo de su clave en el bucket de conocimiento.

La base de conocimientos mezcla normativas con documentación técnica (notas
propias del laboratorio bajo `propio/` y documentación del fabricante bajo
`fortinet/`). Una nota técnica no debe presentarse como si fuera una norma.
"""

from pathlib import Path

import pytest

import reference_kinds

ENGINE_DIR = Path(__file__).resolve().parents[1]


class TestClassify:
    @pytest.mark.parametrize(
        "source",
        [
            "propio/catalogo-endpoints-fortigate.md",
            "propio/campos-fortios-7.6.8.md",
            "fortinet/FortiOS-7.6-Best-Practices.pdf",
            "fortinet/sub/carpeta/cli-reference.pdf",
        ],
    )
    def test_own_notes_and_vendor_documents_are_technical(self, source):
        assert reference_kinds.classify(source) == "technical"

    @pytest.mark.parametrize(
        "source",
        [
            "nist/SP800-53r5.pdf",
            "argentina/Disp-1-2022-DNCIB-Anexo-I.pdf",
            "espana/ens.pdf",
            "disa/fortigate-stig.md",
            "hardening.pdf",
            "normas/fortinet/guia.pdf",
            "propio-de-la-universidad/politica.pdf",
            "fortinet",
        ],
    )
    def test_everything_else_is_normative(self, source):
        assert reference_kinds.classify(source) == "normative"

    @pytest.mark.parametrize("source", ["/propio/nota.md", "  fortinet/a.pdf", "Propio/Nota.md"])
    def test_the_prefix_tolerates_a_leading_slash_spaces_and_case(self, source):
        assert reference_kinds.classify(source) == "technical"

    @pytest.mark.parametrize("source", [None, "", 7, ["propio/a.md"]])
    def test_a_missing_or_unusable_source_is_not_called_technical(self, source):
        assert reference_kinds.classify(source) == "normative"

    def test_the_kinds_are_the_two_published_constants(self):
        assert reference_kinds.TECHNICAL == "technical"
        assert reference_kinds.NORMATIVE == "normative"
        assert reference_kinds.TECHNICAL_PREFIXES == ("propio/", "fortinet/")


class TestPlacement:
    def test_it_is_a_shared_contract_with_no_imports(self):
        module = ENGINE_DIR / "contracts" / "reference_kinds.py"

        assert module.is_file()
        source = module.read_text(encoding="utf-8")
        assert not [ln for ln in source.splitlines() if ln.startswith(("import ", "from "))]
