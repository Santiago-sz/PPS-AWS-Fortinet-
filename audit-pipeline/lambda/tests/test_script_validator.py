"""
Tests para script_validator.py.

Cobertura:
  - Happy path (4.2): script válido pasa; cobertura completa de check_id
    pasa el contract check.
  - Corpus adversarial RED (4.3): cada intento de evasión debe rechazarse
    con un `rule_id` específico, no un rechazo genérico.

Nota de diseño (hallazgo de sdd-explore, CVE-2026-40158): un validador AST
ingenuo que solo inspecciona `ast.Attribute.attr` para detectar dunders es
evadible por reflexión (ej. `getattr(type, "__getattribute__")`, donde el
string peligroso viaja como `ast.Constant`, no como `ast.Attribute`). Este
validador se defiende con allowlist-de-métodos-exactos por receptor
(`fgt`/`report`), no con denylist-de-dunders — por eso incluso
`fgt.__class__` (receptor permitido, atributo no permitido) se rechaza.
"""

import pytest

from script_validator import ValidationResult, validate

VALID_MANIFEST = {
    "run_id": "run-1",
    "checks": [
        {"check_id": "chk1", "title": "Admin lockout", "clause_ref": {}, "endpoints": ["admins"]},
        {"check_id": "chk2", "title": "DNS hardening", "clause_ref": {}, "endpoints": ["dns"]},
    ],
}


def _rule_ids(result: ValidationResult) -> set[str]:
    return {e.rule_id for e in result.errors}


class TestHappyPath:
    def test_valid_script_with_full_control_flow_passes(self):
        source = """
def evaluate():
    admins = fgt.get("admins")
    count = 0
    for admin in admins:
        if isinstance(admin, dict):
            count += 1
    if count > 0:
        report.finding("chk1", "fail", "hay admins configurados")
    else:
        report.finding("chk1", "pass", "sin admins locales")

    dns = fgt.get("dns")
    report.finding("chk2", "pass", "dns configurado", endpoints_used=["dns"])
    report.note("chk2", "revisado manualmente")

evaluate()
"""
        result = validate(source, VALID_MANIFEST)

        assert result.valid is True
        assert result.errors == ()

    def test_full_check_id_coverage_passes_contract_check(self):
        # Covers every check_id in the manifest via report.finding() -> contract check passes.
        source = """
report.finding("chk1", "pass", "ok")
report.finding("chk2", "pass", "ok")
"""
        result = validate(source, VALID_MANIFEST)

        assert result.valid is True

    def test_incomplete_check_id_coverage_fails_contract_check(self):
        # chk2 is never referenced by report.finding() -> contract stage rejects.
        source = """
report.finding("chk1", "pass", "ok")
"""
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "check_id_coverage_incomplete" in _rule_ids(result)
        errors = [e for e in result.errors if e.rule_id == "check_id_coverage_incomplete"]
        assert errors[0].failure_kind == "contract"


class TestSyntaxGate:
    def test_syntax_error_fails_with_syntax_failure_kind(self):
        result = validate("def broken(:\n    pass", VALID_MANIFEST)

        assert result.valid is False
        assert result.errors[0].rule_id == "syntax_error"
        assert result.errors[0].failure_kind == "syntax"


class TestAdversarialCorpus:
    """Each case must reject with ITS OWN specific rule_id — not a generic catch-all."""

    def test_dunder_class_attribute_walk_is_denied(self):
        source = "x = fgt.__class__\n"
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_name:dunder" in _rule_ids(result)

    def test_getattr_reflection_is_denied_by_name(self):
        source = 'x = getattr(fgt, "get")\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_name:builtin" in _rule_ids(result)

    def test_type_dunder_getattribute_reflection_bypass_is_denied(self):
        """
        CVE-2026-40158 vector: `type.__getattribute__(...)` used to try to
        reach attributes without writing a literal `obj.__attr__` — this
        validator's allowlist-of-exact-methods-per-receiver rejects it
        regardless of how the dunder token is spelled in the source.
        """
        source = 'x = type.__getattribute__(fgt, "get")\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        rule_ids = _rule_ids(result)
        # Caught on at least two independent axes: the dunder attribute AND
        # the denied `type` identifier by name.
        assert "denied_name:dunder" in rule_ids
        assert "denied_name:builtin" in rule_ids

    def test_getattr_with_dunder_string_constant_is_still_denied(self):
        """
        The exact CVE-2026-40158 shape: the dangerous token
        "__getattribute__" travels as an ast.Constant string argument, never
        as an ast.Attribute node. A validator relying solely on
        Attribute-node dunder detection would miss this; `getattr` itself
        being on the by-name denylist is what closes the gap.
        """
        source = 'x = getattr(type, "__getattribute__")\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        rule_ids = _rule_ids(result)
        assert "denied_name:builtin" in rule_ids  # getattr AND type

    def test_bare_import_is_denied(self):
        source = "import os\n"
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_node:Import" in _rule_ids(result)

    def test_import_from_is_denied(self):
        source = "from os import path\n"
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_node:ImportFrom" in _rule_ids(result)

    def test_while_loop_is_denied(self):
        source = "while True:\n    pass\n"
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_node:While" in _rule_ids(result)

    def test_try_except_is_denied(self):
        """
        Denying Try is what makes SandboxBudgetExceeded uncatchable by a
        generated script (design.md Decision #6) — this is a load-bearing
        rejection, not incidental.
        """
        source = "try:\n    pass\nexcept Exception:\n    pass\n"
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_node:Try" in _rule_ids(result)

    @pytest.mark.parametrize("builtin_name", ["eval", "exec", "compile", "open"])
    def test_disallowed_builtins_are_denied_by_name(self, builtin_name):
        source = f'x = {builtin_name}("noop")\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_name:builtin" in _rule_ids(result)

    def test_dunder_import_is_denied(self):
        # "__import__" is caught by the dunder rule first (it contains "__"
        # itself) — still a specific, non-generic rejection, just a
        # different axis of the same by-name defense.
        source = 'x = __import__("os")\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_name:dunder" in _rule_ids(result)

    def test_oversized_ast_is_denied(self):
        source = "\n".join(f"v{i} = {i}" for i in range(1500))
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "max_nodes_exceeded" in _rule_ids(result)

    def test_deeply_nested_ast_is_denied(self):
        source = (
            "if True:\n    if True:\n        if True:\n            if True:\n                pass\n"
        )
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "max_nesting_exceeded" in _rule_ids(result)

    def test_non_literal_endpoint_arg_is_denied(self):
        source = 'key = "admins"\nx = fgt.get(key)\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "endpoint_arg_not_literal" in _rule_ids(result)

    def test_unknown_endpoint_literal_is_denied(self):
        source = 'x = fgt.get("not_a_real_endpoint")\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "endpoint_not_in_catalog" in _rule_ids(result)

    def test_unknown_check_id_is_denied(self):
        source = 'report.finding("does_not_exist", "pass", "ok")\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "check_id_unknown" in _rule_ids(result)

    def test_non_literal_check_id_is_denied(self):
        source = 'cid = "chk1"\nreport.finding(cid, "pass", "ok")\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "check_id_not_literal" in _rule_ids(result)

    def test_disallowed_attribute_on_allowed_receiver_is_denied(self):
        """`fgt`/`report` are allowed receivers, but only their allowlisted
        method names — not arbitrary attribute access on them."""
        source = "x = fgt.raw_request\n"
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "attribute_not_allowlisted" in _rule_ids(result)

    def test_attribute_access_on_disallowed_receiver_is_denied(self):
        source = 'x = "".join\n'
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "attribute_not_allowlisted" in _rule_ids(result)

    def test_lambda_is_denied(self):
        source = "f = lambda x: x\n"
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_node:Lambda" in _rule_ids(result)

    def test_class_def_is_denied(self):
        source = "class Foo:\n    pass\n"
        result = validate(source, VALID_MANIFEST)

        assert result.valid is False
        assert "denied_node:ClassDef" in _rule_ids(result)
