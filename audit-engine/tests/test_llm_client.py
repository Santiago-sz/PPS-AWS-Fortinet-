"""
Tests para llm_client.py — fase map (chunk group -> PolicyCheck[]) y fase
reduce (PolicyCheck[] -> script.py), con ciclo de reintento acotado.

Mockea el cliente `bedrock-runtime` (via `bedrock_client.get_client`) —
nunca se llama a Amazon Bedrock real. Cada test puede inspeccionar las
requests Converse capturadas (`messages[0].content[0].text` es el prompt
de usuario enviado).
"""

import hashlib
import json

import pytest
from botocore.exceptions import ClientError

import field_catalog
import fortios_field_catalog
import llm_client
import script_validator
from llm_client import (
    MAP_SYSTEM_PROMPT,
    MAX_GENERATION_ATTEMPTS,
    MAX_MAP_CALLS,
    ClaudeCallError,
    MapCallBudgetExceededError,
    MapResponseParseError,
    _normalize_check,
    build_retry_feedback,
    current_model_id,
    generate_audit_script,
    group_chunks_for_map,
    map_chunks_to_checks,
)
from tests.conftest import bedrock_converse_response, bedrock_json_response

ENDPOINT_CATALOG = ["admins", "dns", "system_global"]


def _make_chunk(chunk_id: str, text: str, heading_path=None, page=1) -> dict:
    return {
        "chunk_id": chunk_id,
        "ordinal": int(chunk_id.split("-")[1]),
        "heading_path": heading_path or ["Articulo 1"],
        "page": page,
        "char_span": [0, len(text)],
        "text": text,
    }


def _mock_bedrock(mocker, responses: list):
    """Reemplaza el cliente Bedrock por un MagicMock que devuelve (o levanta)
    `responses` en orden. Devuelve (client, captured_requests)."""
    client = mocker.MagicMock()
    captured: list[dict] = []

    def fake_converse(**kwargs):
        captured.append(kwargs)
        item = responses[len(captured) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    client.converse.side_effect = fake_converse
    mocker.patch("bedrock_client.get_client", return_value=client)
    return client, captured


def _user_prompt(request: dict) -> str:
    return request["messages"][0]["content"][0]["text"]


VALID_SCRIPT = """\
data = fgt.get("admins")
if data:
    report.finding("chk-0001", "fail", "hay admins configurados")
else:
    report.finding("chk-0001", "pass", "no hay admins configurados")
"""

# Denied node (Import) -> script_validator rejects with failure_kind="allowlist",
# rule_id="denied_node:Import", on line 1.
INVALID_SCRIPT_BAD_IMPORT = """\
import os
report.finding("chk-0001", "fail", "x")
"""


ONE_CHECK_MAP_RESPONSE = {
    "checks": [
        {
            "title": "Admin lockout enabled",
            "clause_ref": {
                "chunk_id": "chunk-0001",
                "heading_path": ["Articulo 1"],
                "page": 1,
                "quote": "Los administradores deben tener bloqueo de cuenta habilitado.",
            },
            "endpoints": ["admins"],
            "severity": "high",
            "intent": "Verify admin lockout",
            "remediation": {
                "summary": "Habilitar el bloqueo de cuenta de administradores.",
                "steps": ["System > Settings > Administration Settings", "Set lockout threshold"],
                "fortigate_cli": "config system global\n    set admin-lockout-threshold 3\nend",
            },
        }
    ]
}

EMPTY_MAP_RESPONSE = {"checks": []}


class TestGroupChunksForMap:
    """Agrupación pura de chunks en grupos para cada llamada de map —
    sin llamadas al modelo, sin mocks."""

    def test_small_chunks_under_budget_form_a_single_group(self):
        chunks = [_make_chunk(f"chunk-{i:04d}", "x" * 100) for i in range(5)]

        groups = group_chunks_for_map(chunks, max_group_chars=10_000)

        assert len(groups) == 1
        assert len(groups[0]) == 5

    def test_chunks_exceeding_budget_split_into_multiple_groups(self):
        chunks = [_make_chunk(f"chunk-{i:04d}", "x" * 600) for i in range(5)]

        groups = group_chunks_for_map(chunks, max_group_chars=1_000)

        # 5 chunks * 600 chars = 3000 chars total, budget 1000/group -> at least 3 groups
        assert len(groups) >= 3
        # never split a chunk itself — every original chunk appears whole in exactly one group
        flattened = [c for group in groups for c in group]
        assert len(flattened) == 5
        assert {c["chunk_id"] for c in flattened} == {c["chunk_id"] for c in chunks}

    def test_a_single_oversized_chunk_still_becomes_its_own_group_never_split(self):
        chunks = [_make_chunk("chunk-0001", "x" * 5000)]

        groups = group_chunks_for_map(chunks, max_group_chars=1_000)

        assert len(groups) == 1
        assert groups[0][0]["text"] == "x" * 5000  # never truncated


class TestModelResolution:
    def test_current_model_id_follows_env_override(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
        assert current_model_id() == "us.anthropic.claude-sonnet-4-6"
        monkeypatch.setenv("BEDROCK_MODEL_ID", "eu.anthropic.claude-sonnet-4-6")
        assert current_model_id() == "eu.anthropic.claude-sonnet-4-6"

    def test_map_prompt_describes_remediation_as_a_non_executed_proposal(self):
        assert '"remediation"' in MAP_SYSTEM_PROMPT
        assert '"fortigate_cli"' in MAP_SYSTEM_PROMPT
        assert "NUNCA ejecuta" in MAP_SYSTEM_PROMPT
        assert all(len(line) <= 100 for line in MAP_SYSTEM_PROMPT.splitlines())


class TestNormalizeCheck:
    def test_missing_remediation_gets_canonical_empty_shape(self):
        check = {"title": "t", "endpoints": ["dns"]}

        normalized = _normalize_check(check)

        assert normalized["remediation"] == {"summary": None, "steps": [], "fortigate_cli": None}
        assert normalized["title"] == "t"
        assert "remediation" not in check  # input never mutated

    def test_string_remediation_is_coerced_into_summary(self):
        normalized = _normalize_check({"remediation": "  Habilitar MFA  "})

        assert normalized["remediation"] == {
            "summary": "Habilitar MFA",
            "steps": [],
            "fortigate_cli": None,
        }

    def test_partial_dict_is_completed_and_cleaned(self):
        normalized = _normalize_check(
            {"remediation": {"summary": "x", "steps": ["a", "", None, " b "], "fortigate_cli": ""}}
        )

        assert normalized["remediation"] == {
            "summary": "x",
            "steps": ["a", "b"],
            "fortigate_cli": None,
        }

    def test_single_string_step_becomes_a_list(self):
        normalized = _normalize_check({"remediation": {"steps": "solo un paso"}})

        assert normalized["remediation"]["steps"] == ["solo un paso"]

    def test_garbage_remediation_type_falls_back_to_empty_shape(self):
        normalized = _normalize_check({"remediation": 42})

        assert normalized["remediation"] == {"summary": None, "steps": [], "fortigate_cli": None}

    def test_full_remediation_passes_through_unchanged(self):
        remediation = ONE_CHECK_MAP_RESPONSE["checks"][0]["remediation"]

        normalized = _normalize_check({"remediation": dict(remediation)})

        assert normalized["remediation"] == remediation


class TestMapCallBudget:
    def test_map_call_budget_exceeded_fails_explicitly_before_any_model_call(self, mocker):
        # 20 chunks of 600 chars each with a tiny per-group budget forces > MAX_MAP_CALLS groups
        chunks = [_make_chunk(f"chunk-{i:04d}", "x" * 600) for i in range(20)]
        client, _ = _mock_bedrock(mocker, [])

        with pytest.raises(MapCallBudgetExceededError):
            map_chunks_to_checks(
                chunks,
                ENDPOINT_CATALOG,
                max_map_calls=2,
                max_group_chars=1_000,
            )

        # explicit failure BEFORE any model call — never silently truncate to fit
        client.converse.assert_not_called()

    def test_default_max_map_calls_constant_is_twelve(self):
        assert MAX_MAP_CALLS == 12


class TestMapChunksToChecks:
    def test_map_produces_policy_checks_with_assigned_check_ids(self, mocker):
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        _, captured = _mock_bedrock(mocker, [bedrock_json_response(ONE_CHECK_MAP_RESPONSE)])

        checks = map_chunks_to_checks(chunks, ENDPOINT_CATALOG)

        assert len(checks) == 1
        assert checks[0]["check_id"] == "chk-0001"
        assert checks[0]["title"] == "Admin lockout enabled"
        assert checks[0]["clause_ref"]["chunk_id"] == "chunk-0001"
        assert checks[0]["endpoints"] == ["admins"]
        assert checks[0]["remediation"]["fortigate_cli"].startswith("config system global")

        # the map request goes to the resolved model with an explicit maxTokens
        assert captured[0]["modelId"] == current_model_id()
        assert captured[0]["inferenceConfig"]["maxTokens"] == llm_client.MAP_MAX_TOKENS
        assert captured[0]["system"][0]["text"] == MAP_SYSTEM_PROMPT

    def test_map_normalizes_checks_missing_remediation(self, mocker):
        chunks = [_make_chunk("chunk-0001", "texto")]
        response = {
            "checks": [
                {"title": "sin remediacion", "endpoints": ["dns"], "severity": "low"},
                "esto no es un dict y se descarta",
            ]
        }
        _mock_bedrock(mocker, [bedrock_json_response(response)])

        checks = map_chunks_to_checks(chunks, ENDPOINT_CATALOG)

        assert len(checks) == 1
        assert checks[0]["remediation"] == {"summary": None, "steps": [], "fortigate_cli": None}

    def test_map_does_not_truncate_large_chunk_text_in_the_request(self, mocker):
        large_text = "Articulo largo. " * 2000  # well over any legacy MAX_DATA_CHARS-style limit
        chunks = [_make_chunk("chunk-0001", large_text)]
        _, captured = _mock_bedrock(mocker, [bedrock_json_response(EMPTY_MAP_RESPONSE)])

        map_chunks_to_checks(chunks, ENDPOINT_CATALOG)

        sent_prompt = _user_prompt(captured[0])
        assert large_text in sent_prompt
        assert "truncad" not in sent_prompt.lower()

    def test_non_json_map_response_raises_parse_error(self, mocker):
        chunks = [_make_chunk("chunk-0001", "texto")]
        _mock_bedrock(mocker, [bedrock_converse_response("no soy json")])

        with pytest.raises(MapResponseParseError):
            map_chunks_to_checks(chunks, ENDPOINT_CATALOG)

    def test_map_response_wrapped_in_code_fences_is_parsed(self, mocker):
        # Observado en vivo (2026-11-18): el modelo a veces envuelve el JSON
        # de la fase map en un bloque ```json ... ```, aunque el prompt pida
        # JSON puro. El contenido es válido y no debe descartarse.
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        fenced = "```json\n" + json.dumps(ONE_CHECK_MAP_RESPONSE) + "\n```"
        _mock_bedrock(mocker, [bedrock_converse_response(fenced)])

        checks = map_chunks_to_checks(chunks, ENDPOINT_CATALOG)

        assert len(checks) == 1
        assert checks[0]["title"] == "Admin lockout enabled"

    def test_fenced_map_response_with_invalid_json_still_raises_parse_error(self, mocker):
        chunks = [_make_chunk("chunk-0001", "texto")]
        _mock_bedrock(mocker, [bedrock_converse_response("```json\nno soy json\n```")])

        with pytest.raises(MapResponseParseError):
            map_chunks_to_checks(chunks, ENDPOINT_CATALOG)

    def test_truncated_map_response_fails_explicitly(self, mocker):
        # Observado en el primer E2E con una normativa real (2026-11-18): un
        # grupo con muchos controles agotó el tope de salida y el JSON llegó
        # cortado. Debe informarse como truncamiento, no como JSON inválido,
        # y nunca usarse un resultado parcial.
        chunks = [_make_chunk("chunk-0001", "texto")]
        cut = json.dumps(ONE_CHECK_MAP_RESPONSE)[:-20]
        _mock_bedrock(mocker, [bedrock_converse_response(cut, stop_reason="max_tokens")])

        with pytest.raises(llm_client.MapOutputTruncatedError) as excinfo:
            map_chunks_to_checks(chunks, ENDPOINT_CATALOG)

        assert isinstance(excinfo.value, MapResponseParseError)
        assert "max_tokens" in str(excinfo.value)

    def test_complete_map_response_at_other_stop_reasons_is_parsed(self, mocker):
        chunks = [_make_chunk("chunk-0001", "texto")]
        _mock_bedrock(mocker, [bedrock_json_response(ONE_CHECK_MAP_RESPONSE)])

        assert len(map_chunks_to_checks(chunks, ENDPOINT_CATALOG)) == 1

    def test_bedrock_failure_surfaces_as_claude_call_error(self, mocker):
        chunks = [_make_chunk("chunk-0001", "texto")]
        _mock_bedrock(
            mocker,
            [
                ClientError(
                    {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
                    "Converse",
                )
            ],
        )

        with pytest.raises(ClaudeCallError) as exc:
            map_chunks_to_checks(chunks, ENDPOINT_CATALOG)

        assert "ThrottlingException" in str(exc.value)


class TestBuildRetryFeedback:
    """Feedback puro derivado de un ValidationResult — sin llamadas al modelo."""

    def test_builds_feedback_dict_from_first_validation_error(self):
        result = script_validator.validate(INVALID_SCRIPT_BAD_IMPORT, {"checks": []})
        assert not result.valid

        feedback = build_retry_feedback(1, INVALID_SCRIPT_BAD_IMPORT, result)

        assert feedback["attempt"] == 1
        assert feedback["failure_kind"] == "allowlist"
        assert feedback["rule_id"] == "denied_node:Import"
        assert "import" in feedback["message"].lower() or "Import" in feedback["message"]
        assert feedback["line"] == 1
        assert "import os" in feedback["snippet"]

    def test_feedback_snippet_is_none_when_error_has_no_line(self):
        # contract errors (missing coverage) carry no line number: script only
        # reports chk-0001, manifest also expects chk-0002 -> coverage gap
        manifest = {
            "checks": [
                {"check_id": "chk-0001", "title": "x"},
                {"check_id": "chk-0002", "title": "y"},
            ]
        }
        result = script_validator.validate(VALID_SCRIPT, manifest)
        assert not result.valid
        assert result.errors[0].rule_id == "check_id_coverage_incomplete"

        feedback = build_retry_feedback(2, VALID_SCRIPT, result)

        assert feedback["attempt"] == 2
        assert feedback["line"] is None
        assert feedback["snippet"] is None


def _events(capsys, name: str) -> list[dict]:
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.get("event") == name]


class TestGenerateAuditScriptStandard:
    def test_standard_generation_produces_a_read_only_valid_script(self, mocker, capsys):
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        _, captured = _mock_bedrock(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(VALID_SCRIPT),
            ],
        )

        result = generate_audit_script(chunks, ENDPOINT_CATALOG)

        assert result["status"] == "ok"
        assert result["attempts"] == 1
        assert "fgt.get(" in result["script"]
        assert "report.finding(" in result["script"]
        # never a write/delete/config-changing call — read-only by construction,
        # confirmed by re-running the same validator the sandbox would use
        validation = script_validator.validate(result["script"], {"checks": result["checks"]})
        assert validation.valid

        # reduce prompt never leaks the remediation proposal into the script generator
        assert "fortigate_cli" not in _user_prompt(captured[1])

        events = _events(capsys, "generation_result")
        assert len(events) == 1
        assert events[0]["success"] is True
        assert events[0]["attempts_used"] == 1
        assert events[0]["failure_kinds_per_attempt"] == []


class TestGenerateAuditScriptRetry:
    def test_invalid_script_triggers_exactly_one_retry_with_correct_feedback(self, mocker, capsys):
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        _, captured = _mock_bedrock(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(INVALID_SCRIPT_BAD_IMPORT),
                bedrock_converse_response(VALID_SCRIPT),
            ],
        )

        result = generate_audit_script(chunks, ENDPOINT_CATALOG)

        assert result["status"] == "ok"
        assert result["attempts"] == 2

        # 3 model calls total: 1 map + 2 reduce (1 initial + 1 retry)
        assert len(captured) == 3
        retry_prompt = _user_prompt(captured[2])
        assert "denied_node:Import" in retry_prompt
        assert "intento 1" in retry_prompt  # feedback references the failed attempt
        assert "import os" in retry_prompt  # previous script included verbatim

        events = _events(capsys, "generation_result")
        assert events[0]["success"] is True
        assert events[0]["attempts_used"] == 2
        assert events[0]["failure_kinds_per_attempt"] == [["allowlist"]]

    def test_retry_budget_exhausted_after_three_attempts_returns_generation_failed(
        self, mocker, capsys
    ):
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        _mock_bedrock(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(INVALID_SCRIPT_BAD_IMPORT),
                bedrock_converse_response(INVALID_SCRIPT_BAD_IMPORT),
                bedrock_converse_response(INVALID_SCRIPT_BAD_IMPORT),
            ],
        )

        result = generate_audit_script(chunks, ENDPOINT_CATALOG)

        assert result["status"] == "generation_failed"
        assert result["attempts"] == MAX_GENERATION_ATTEMPTS
        assert result["errors"][0]["rule_id"] == "denied_node:Import"
        # never executed / never returned as a usable script
        assert "script" not in result

        events = _events(capsys, "generation_result")
        assert events[0]["success"] is False
        assert events[0]["attempts_used"] == MAX_GENERATION_ATTEMPTS
        assert events[0]["failure_kinds_per_attempt"] == [["allowlist"]] * 3

    def test_reduce_requests_carry_stage_and_attempt_in_llm_call_events(self, mocker, capsys):
        chunks = [_make_chunk("chunk-0001", "texto")]
        _mock_bedrock(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(INVALID_SCRIPT_BAD_IMPORT),
                bedrock_converse_response(VALID_SCRIPT),
            ],
        )

        generate_audit_script(chunks, ENDPOINT_CATALOG)

        calls = _events(capsys, "llm_call")
        assert [(c["stage"], c["attempt"]) for c in calls] == [
            ("map", None),
            ("reduce", 1),
            ("reduce", 2),
        ]


class TestGenerateAuditScriptNoVerifiableControls:
    def test_empty_policy_checks_reports_no_verifiable_controls_without_calling_reduce(
        self, mocker
    ):
        chunks = [_make_chunk("chunk-0001", "Texto sin controles FortiGate-verificables.")]
        client, _ = _mock_bedrock(mocker, [bedrock_json_response(EMPTY_MAP_RESPONSE)])

        result = generate_audit_script(chunks, ENDPOINT_CATALOG)

        assert result["status"] == "no_verifiable_controls"
        assert result["checks"] == []
        # exactly one model call (the map call) — reduce is never invoked
        assert client.converse.call_count == 1


# ---------------------------------------------------------------------------
# Documentación de referencia (Knowledge Base) en la fase reduce
# ---------------------------------------------------------------------------

REFERENCE_SECTION = (
    "=== INICIO DOCUMENTACION DE REFERENCIA ===\n"
    "--- check_id=chk-0001 ---\n"
    "[fuente: fortinet/hardening.pdf | puntaje: 0.9000]\n"
    "texto-de-referencia-recuperado\n"
    "=== FIN DOCUMENTACION DE REFERENCIA ==="
)
KNOWLEDGE_BASE_BLOCK = {
    "enabled": True,
    "controls_with_references": 1,
    "retrievals_failed": 0,
    "references": {"chk-0001": [{"source": "fortinet/hardening.pdf", "score": 0.9}]},
}


class _References:
    """Doble de `reference_context.ReferenceContext` (misma interfaz)."""

    def __init__(self, prompt_section=REFERENCE_SECTION, manifest_block=None):
        self.prompt_section = prompt_section
        self.manifest_block = manifest_block or KNOWLEDGE_BASE_BLOCK


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _system_prompt(request: dict) -> str:
    return request["system"][0]["text"]


GOLDEN_CHECKS = [
    {
        "check_id": "chk-0001",
        "title": "Admin lockout",
        "clause_ref": {
            "chunk_id": "chunk-0001",
            "heading_path": ["Articulo 1"],
            "page": 1,
            "quote": "Los administradores deben tener bloqueo de cuenta.",
        },
        "endpoints": ["admins"],
        "severity": "high",
        "intent": "Verify admin lockout",
    }
]
GOLDEN_RETRY_FEEDBACK = {
    "attempt": 1,
    "failure_kind": "allowlist",
    "rule_id": "denied_node:Import",
    "message": "m",
    "line": 1,
    "col": 0,
    "snippet": "import os",
    "previous_script": "import os\n",
}


class TestPromptsWithoutKnowledgeBaseAreByteIdentical:
    """Hashes calculados sobre el commit e86bbc1, antes de conectar la
    recuperación. Con la Knowledge Base deshabilitada ningún prompt cambia.

    Desde el catálogo de campos (decisión 13) el system prompt de reduce es
    `REDUCE_SYSTEM_PROMPT` más `FIELD_CATALOG_SYSTEM_NOTE`, con o sin Knowledge
    Base. El texto base y el prompt de map conservan su hash."""

    def test_system_prompts_are_unchanged(self):
        # El hash de REDUCE_SYSTEM_PROMPT se actualizó de forma deliberada el
        # 2026-11-18 (antes cd045c41…, calculado sobre e86bbc1). La primera
        # corrida en vivo mostró que el modelo usaba métodos de dict/list/str
        # y cadenas elif que el validador rechaza; el prompt ahora describe
        # esas restricciones. El validador no cambió. Este test sigue fijando
        # que habilitar o no la Knowledge Base no altera el prompt base.
        assert _sha256(llm_client.REDUCE_SYSTEM_PROMPT) == (
            "dad11799c122f324d5265351f1772ddbebf62e1fe386007333d20eb67dce219a"
        )
        assert _sha256(MAP_SYSTEM_PROMPT) == (
            "5c0d6b7cc69a18cf10da46f06d597b213b90f060964abbab221a4bd1c7180704"
        )

    def test_reduce_user_prompt_is_unchanged(self):
        prompt = llm_client._build_reduce_user_prompt(GOLDEN_CHECKS, ENDPOINT_CATALOG, None)
        retry = llm_client._build_reduce_user_prompt(
            GOLDEN_CHECKS, ENDPOINT_CATALOG, dict(GOLDEN_RETRY_FEEDBACK)
        )

        assert _sha256(prompt) == "d1da5f83aa4ae6e14651f85b0f3fc4dd8b59729e5c65e36c73d5600d956a771f"
        assert _sha256(retry) == "b7e32e21d041cce9fa1fceebbd7f477b1eeeb13a8cfd65f4b1670d23ad30ca7c"

    def test_generation_without_provider_sends_the_original_prompts_and_no_block(self, mocker):
        _, captured = _mock_bedrock(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(VALID_SCRIPT),
            ],
        )

        result = generate_audit_script([_make_chunk("chunk-0001", "texto")], ENDPOINT_CATALOG)

        assert result["status"] == "ok"
        assert "knowledge_base" not in result
        assert _system_prompt(captured[0]) == MAP_SYSTEM_PROMPT
        assert _system_prompt(captured[1]) == (
            llm_client.REDUCE_SYSTEM_PROMPT + llm_client.FIELD_CATALOG_SYSTEM_NOTE
        )
        assert _user_prompt(captured[1]) == llm_client._build_reduce_user_prompt(
            result["checks"], ENDPOINT_CATALOG, None
        )
        assert "DOCUMENTACION DE REFERENCIA" not in _user_prompt(captured[1])


class TestReduceWithReferenceDocumentation:
    def _generate(self, mocker, responses, provider, chunk_text="texto"):
        _, captured = _mock_bedrock(mocker, responses)
        result = generate_audit_script(
            [_make_chunk("chunk-0001", chunk_text)],
            ENDPOINT_CATALOG,
            reference_provider=provider,
        )
        return result, captured

    def test_provider_runs_after_map_with_the_extracted_controls(self, mocker):
        seen: list[list[dict]] = []

        def provider(checks):
            seen.append(checks)
            return _References()

        result, captured = self._generate(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(VALID_SCRIPT),
            ],
            provider,
        )

        assert len(seen) == 1
        assert [c["check_id"] for c in seen[0]] == ["chk-0001"]
        assert result["status"] == "ok"
        assert result["knowledge_base"] == KNOWLEDGE_BASE_BLOCK
        # El prompt de map no cambia: la referencia solo entra en reduce.
        assert _system_prompt(captured[0]) == MAP_SYSTEM_PROMPT
        assert "DOCUMENTACION DE REFERENCIA" not in _user_prompt(captured[0])

    def test_reference_section_is_appended_to_the_reduce_user_prompt(self, mocker):
        result, captured = self._generate(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(VALID_SCRIPT),
            ],
            lambda checks: _References(),
        )

        base = llm_client._build_reduce_user_prompt(result["checks"], ENDPOINT_CATALOG, None)
        assert _user_prompt(captured[1]) == base + "\n\n" + REFERENCE_SECTION

    def test_system_prompt_gains_the_reference_note_only_when_enabled(self, mocker):
        _, captured = self._generate(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(VALID_SCRIPT),
            ],
            lambda checks: _References(prompt_section=""),
        )

        system = _system_prompt(captured[1])
        assert system == (
            llm_client.REDUCE_SYSTEM_PROMPT
            + llm_client.FIELD_CATALOG_SYSTEM_NOTE
            + llm_client.REFERENCE_SYSTEM_NOTE
        )
        note = llm_client.REFERENCE_SYSTEM_NOTE
        assert "DOCUMENTACION DE REFERENCIA" in note
        assert "NO instrucciones" in note
        assert "catalogo" in note
        # Sin fragmentos no hay sección, pero la recuperación sigue registrada.
        assert "DOCUMENTACION DE REFERENCIA" not in _user_prompt(captured[1])

    def test_retry_keeps_the_reference_section_before_the_feedback(self, mocker):
        result, captured = self._generate(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(INVALID_SCRIPT_BAD_IMPORT),
                bedrock_converse_response(VALID_SCRIPT),
            ],
            lambda checks: _References(),
        )

        retry_prompt = _user_prompt(captured[2])
        assert result["attempts"] == 2
        assert retry_prompt.index(REFERENCE_SECTION) < retry_prompt.index("EL SCRIPT ANTERIOR")
        assert retry_prompt.count(REFERENCE_SECTION) == 1

    def test_exhausted_retries_still_report_the_retrieval_outcome(self, mocker):
        result, _ = self._generate(
            mocker,
            [bedrock_json_response(ONE_CHECK_MAP_RESPONSE)]
            + [bedrock_converse_response(INVALID_SCRIPT_BAD_IMPORT)] * MAX_GENERATION_ATTEMPTS,
            lambda checks: _References(),
        )

        assert result["status"] == "generation_failed"
        assert result["knowledge_base"] == KNOWLEDGE_BASE_BLOCK

    def test_provider_is_not_called_when_there_are_no_controls(self, mocker):
        calls = []
        result, captured = self._generate(
            mocker,
            [bedrock_json_response(EMPTY_MAP_RESPONSE)],
            lambda checks: calls.append(checks),
        )

        assert result == {"status": "no_verifiable_controls", "checks": []}
        assert calls == []
        assert len(captured) == 1

    def test_policy_text_is_never_truncated_when_references_are_enabled(self, mocker):
        """Regla 7 de AGENTS.md: los topes de la referencia nunca recortan la
        normativa ni los controles."""
        big_text = "clausula " + "x" * 60_000 + " fin-de-clausula"
        result, captured = self._generate(
            mocker,
            [
                bedrock_json_response(ONE_CHECK_MAP_RESPONSE),
                bedrock_converse_response(VALID_SCRIPT),
            ],
            lambda checks: _References(prompt_section="R" * 50_000),
            chunk_text=big_text,
        )

        assert big_text in _user_prompt(captured[0])
        reduce_prompt = _user_prompt(captured[1])
        base = llm_client._build_reduce_user_prompt(result["checks"], ENDPOINT_CATALOG, None)
        assert reduce_prompt.startswith(base)
        assert len(result["checks"]) == 1


# ---------------------------------------------------------------------------
# Catálogo de campos (decisión 13): prompt, pista de corrección y registro
# ---------------------------------------------------------------------------

# Válidos para `script_validator`, pero leen un campo que el catálogo no
# lista para `admins`. Los nombres son inventados a propósito.
SCRIPT_TWO_UNKNOWN_FIELDS = """\
data = fgt.get("admins")
flags = [a["invented-flag"] for a in data] + [a["invented-mode"] for a in data]
report.finding("chk-0001", "pass", str(len(flags)))
"""

SCRIPT_ONE_UNKNOWN_FIELD = """\
data = fgt.get("admins")
flags = [a["invented-flag"] for a in data]
report.finding("chk-0001", "pass", str(len(flags)))
"""

SCRIPT_KNOWN_FIELDS = """\
data = fgt.get("admins")
names = [a["name"] for a in data]
report.finding("chk-0001", "pass", str(len(names)))
"""


def _generate(mocker, scripts: list, **options):
    """Corre el pipeline con una respuesta de map y los `scripts` dados como
    respuestas sucesivas de reduce (un `Exception` se levanta)."""
    responses = [bedrock_json_response(ONE_CHECK_MAP_RESPONSE)]
    responses += [
        item if isinstance(item, Exception) else bedrock_converse_response(item) for item in scripts
    ]
    _, captured = _mock_bedrock(mocker, responses)
    result = generate_audit_script(
        [_make_chunk("chunk-0001", "texto")], ENDPOINT_CATALOG, **options
    )
    return result, captured


def _throttling() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"
    )


def _all_events(out: str, name: str) -> list[dict]:
    lines = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.get("event") == name]


class TestFieldCatalogInTheReducePrompt:
    def test_the_note_is_the_section_of_the_versioned_catalogue(self):
        assert llm_client.FIELD_CATALOG_SYSTEM_NOTE == field_catalog.prompt_section()

    def test_the_reduce_system_prompt_states_the_catalogue_and_its_version(self, mocker):
        _, captured = _generate(mocker, [VALID_SCRIPT])

        system = _system_prompt(captured[1])
        version = fortios_field_catalog.CATALOG["fortios_version"]
        assert system.startswith(llm_client.REDUCE_SYSTEM_PROMPT)
        assert f"FortiOS {version}" in system
        assert "- log_settings (objeto): " in system
        assert "- dhcp_servers (sin verificar)" in system
        assert "NO adivines" in system

    def test_the_catalogue_goes_before_the_cache_point_and_not_in_the_user_prompt(self, mocker):
        _, captured = _generate(mocker, [VALID_SCRIPT])

        request = captured[1]
        assert "fwpolicy-implicit-log" in request["system"][0]["text"]
        assert request["system"][1] == {"cachePoint": {"type": "default"}}
        assert "fwpolicy-implicit-log" not in _user_prompt(request)

    def test_the_system_prompt_is_identical_across_attempts(self, mocker):
        _, captured = _generate(
            mocker, [INVALID_SCRIPT_BAD_IMPORT, SCRIPT_ONE_UNKNOWN_FIELD, VALID_SCRIPT]
        )

        assert len(captured) == 4
        assert len({_system_prompt(request) for request in captured[1:]}) == 1

    def test_the_map_prompt_does_not_carry_the_catalogue(self, mocker):
        _, captured = _generate(mocker, [VALID_SCRIPT])

        assert _system_prompt(captured[0]) == MAP_SYSTEM_PROMPT
        assert "CATALOGO DE CAMPOS" not in _user_prompt(captured[0])


class TestUnknownFieldCorrection:
    def test_a_script_without_unknown_fields_costs_no_extra_call(self, mocker, capsys):
        result, captured = _generate(mocker, [SCRIPT_KNOWN_FIELDS])

        assert result["status"] == "ok"
        assert result["attempts"] == 1
        assert len(captured) == 2
        assert result["field_catalog"] == {
            "fortios_version": fortios_field_catalog.CATALOG["fortios_version"],
            "unknown_field_references": 0,
            "references": [],
            "reduce_calls": 1,
        }
        checks = _events(capsys, "field_catalog_check")
        assert [(c["attempt"], c["unknown_field_references"]) for c in checks] == [(1, 0)]

    def test_unknown_fields_are_fed_back_as_a_correction_hint(self, mocker):
        result, captured = _generate(mocker, [SCRIPT_ONE_UNKNOWN_FIELD, SCRIPT_KNOWN_FIELDS])

        assert result["status"] == "ok"
        assert result["script"] == SCRIPT_KNOWN_FIELDS.strip()
        assert result["attempts"] == 2
        assert result["field_catalog"]["unknown_field_references"] == 0
        assert result["field_catalog"]["reduce_calls"] == 2

        hint = _user_prompt(captured[2])
        assert '"invented-flag"' in hint
        assert "admins" in hint
        assert "intento 1" in hint
        assert "NO figuran" in hint
        assert '"indeterminate"' in hint
        assert 'a["invented-flag"]' in hint  # el script anterior viaja completo
        # No es un rechazo del validador y no se presenta como tal.
        assert "FUE RECHAZADO" not in hint
        assert "failure_kind" not in hint

    def test_a_script_that_keeps_an_unknown_field_is_still_accepted(self, mocker, capsys):
        result, _ = _generate(
            mocker, [SCRIPT_TWO_UNKNOWN_FIELDS, SCRIPT_ONE_UNKNOWN_FIELD, SCRIPT_ONE_UNKNOWN_FIELD]
        )

        assert result["status"] == "ok"
        assert result["script"] == SCRIPT_ONE_UNKNOWN_FIELD.strip()
        assert result["attempts"] == 2
        assert result["field_catalog"]["unknown_field_references"] == 1
        assert result["field_catalog"]["references"] == [
            {"field": "invented-flag", "endpoints": ["admins"], "line": 2}
        ]
        assert result["field_catalog"]["reduce_calls"] == 3
        events = _events(capsys, "generation_result")
        assert events[0]["success"] is True
        assert events[0]["unknown_field_references"] == 1

    def test_the_correction_stops_when_it_does_not_reduce_the_unknown_fields(self, mocker):
        result, captured = _generate(
            mocker, [SCRIPT_ONE_UNKNOWN_FIELD, SCRIPT_ONE_UNKNOWN_FIELD, SCRIPT_KNOWN_FIELDS]
        )

        # Dos llamadas de reduce: la tercera no se pide.
        assert len(captured) == 3
        assert result["status"] == "ok"
        assert result["attempts"] == 1
        assert result["field_catalog"]["unknown_field_references"] == 1

    def test_the_correction_never_exceeds_the_attempt_budget(self, mocker):
        result, captured = _generate(
            mocker, [SCRIPT_TWO_UNKNOWN_FIELDS, SCRIPT_KNOWN_FIELDS], max_attempts=1
        )

        assert len(captured) == 2
        assert result["status"] == "ok"
        assert result["attempts"] == 1
        assert result["field_catalog"]["unknown_field_references"] == 2

    def test_a_rejected_correction_falls_back_to_the_valid_script(self, mocker, capsys):
        result, captured = _generate(
            mocker, [SCRIPT_ONE_UNKNOWN_FIELD, INVALID_SCRIPT_BAD_IMPORT, SCRIPT_KNOWN_FIELDS]
        )

        assert result["status"] == "ok"
        assert result["script"] == SCRIPT_ONE_UNKNOWN_FIELD.strip()
        assert result["attempts"] == 1
        assert len(captured) == 3  # no se pide un tercer intento
        assert result["field_catalog"]["unknown_field_references"] == 1
        abandoned = _events(capsys, "field_correction_abandoned")
        assert [(e["attempt"], e["reason"]) for e in abandoned] == [(2, "validator_rejected")]

    def test_a_failed_model_call_during_correction_falls_back_to_the_valid_script(
        self, mocker, capsys
    ):
        result, _ = _generate(mocker, [SCRIPT_ONE_UNKNOWN_FIELD, _throttling()])

        assert result["status"] == "ok"
        assert result["script"] == SCRIPT_ONE_UNKNOWN_FIELD.strip()
        assert result["attempts"] == 1
        abandoned = _events(capsys, "field_correction_abandoned")
        assert [(e["attempt"], e["reason"]) for e in abandoned] == [(2, "model_call_failed")]

    def test_a_failed_model_call_before_any_valid_script_still_raises(self, mocker):
        with pytest.raises(ClaudeCallError):
            _generate(mocker, [INVALID_SCRIPT_BAD_IMPORT, _throttling()])

    def test_validator_rejections_keep_their_own_feedback_and_budget(self, mocker):
        result, captured = _generate(
            mocker, [INVALID_SCRIPT_BAD_IMPORT, SCRIPT_ONE_UNKNOWN_FIELD, SCRIPT_KNOWN_FIELDS]
        )

        assert result["status"] == "ok"
        assert result["attempts"] == 3
        assert "FUE RECHAZADO" in _user_prompt(captured[2])
        assert "NO figuran" in _user_prompt(captured[3])
        assert "FUE RECHAZADO" not in _user_prompt(captured[3])

    def test_exhausted_validator_retries_still_fail_without_a_catalogue_block(self, mocker):
        result, _ = _generate(mocker, [INVALID_SCRIPT_BAD_IMPORT] * MAX_GENERATION_ATTEMPTS)

        assert result["status"] == "generation_failed"
        assert "script" not in result
        assert "field_catalog" not in result

    def test_the_first_attempt_metric_still_means_the_validator_accepted_it(self, mocker, capsys):
        result, _ = _generate(mocker, [SCRIPT_ONE_UNKNOWN_FIELD, SCRIPT_KNOWN_FIELDS])

        assert result["attempts"] == 2
        assert result["first_valid_attempt"] == 1
        lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        first_pass = [ln for ln in lines if "GenerationFirstAttemptPass" in ln]
        unknown = [ln for ln in lines if "GenerationUnknownFieldReferences" in ln]
        assert [ln["GenerationFirstAttemptPass"] for ln in first_pass] == [1]
        assert [ln["GenerationUnknownFieldReferences"] for ln in unknown] == [0]

    def test_the_hint_lists_a_bounded_number_of_fields(self):
        references = [
            {"field": f"invented-{i}", "endpoints": ["admins"], "line": i + 1} for i in range(45)
        ]
        feedback = llm_client.build_field_feedback(1, "previous = 1\n", references)

        prompt = llm_client._build_reduce_user_prompt(GOLDEN_CHECKS, ENDPOINT_CATALOG, feedback)

        listed = [ln for ln in prompt.splitlines() if ln.startswith('  - "invented-')]
        assert len(listed) == field_catalog.MAX_LISTED_REFERENCES
        assert f"y {45 - field_catalog.MAX_LISTED_REFERENCES} mas" in prompt

    def test_the_field_check_events_carry_names_and_never_the_script(self, mocker, capsys):
        _generate(mocker, [SCRIPT_ONE_UNKNOWN_FIELD, SCRIPT_KNOWN_FIELDS])

        out = capsys.readouterr().out
        checks = _all_events(out, "field_catalog_check")
        assert checks[0]["references"] == [
            {"field": "invented-flag", "endpoints": ["admins"], "line": 2}
        ]
        assert "fgt.get" not in out
        assert "report.finding" not in out


class TestRejectedAttemptLogging:
    def test_a_rejected_attempt_logs_what_the_validator_rejected(self, mocker, capsys):
        _generate(mocker, [INVALID_SCRIPT_BAD_IMPORT, VALID_SCRIPT])

        events = _events(capsys, "generation_attempt_rejected")
        assert len(events) == 1
        event = events[0]
        assert event["attempt"] == 1
        assert event["failure_kinds"] == ["allowlist"]
        assert event["error_count"] == 1
        assert event["errors"] == [
            {
                "rule_id": "denied_node:Import",
                "failure_kind": "allowlist",
                "message": "'Import' is not allowed",
                "line": 1,
                "col": 0,
            }
        ]

    def test_every_rejected_attempt_is_logged(self, mocker, capsys):
        _generate(mocker, [INVALID_SCRIPT_BAD_IMPORT] * MAX_GENERATION_ATTEMPTS)

        events = _events(capsys, "generation_attempt_rejected")
        assert [e["attempt"] for e in events] == [1, 2, 3]

    def test_the_script_body_is_never_logged(self, mocker, capsys):
        marker = "MARCADOR_DEL_CUERPO_DEL_SCRIPT"
        script = f'import os\nvalue = "{marker}"\nreport.finding("chk-0001", "fail", value)\n'

        _generate(mocker, [script, VALID_SCRIPT])

        out = capsys.readouterr().out
        assert "generation_attempt_rejected" in out
        assert marker not in out
        assert "import os" not in out

    def test_a_syntax_error_is_logged_without_the_offending_line(self, mocker, capsys):
        script = 'value = "MARCADOR_DE_LINEA" +\nreport.finding("chk-0001", "fail", "x")\n'

        _generate(mocker, [script, VALID_SCRIPT])

        out = capsys.readouterr().out
        events = _all_events(out, "generation_attempt_rejected")
        assert events[0]["failure_kinds"] == ["syntax"]
        assert events[0]["errors"][0]["rule_id"] == "syntax_error"
        assert events[0]["errors"][0]["line"] == 1
        assert "MARCADOR_DE_LINEA" not in out

    def test_long_messages_and_long_error_lists_are_truncated(self, mocker, capsys):
        long_name = "x" * 600
        lines = [f"import m{i}" for i in range(40)]
        lines.append(f"{long_name}.call()")
        lines.append('report.finding("chk-0001", "fail", "x")')

        _generate(mocker, ["\n".join(lines) + "\n", VALID_SCRIPT])

        event = _events(capsys, "generation_attempt_rejected")[0]
        assert event["error_count"] == 41
        assert len(event["errors"]) == llm_client.MAX_LOGGED_VALIDATION_ERRORS
        assert all(
            len(error["message"]) <= llm_client.MAX_LOGGED_MESSAGE_CHARS
            for error in event["errors"]
        )

    def test_a_long_message_is_cut_to_the_limit(self):
        error = script_validator.ValidationError(
            rule_id="r" * 400, failure_kind="allowlist", message="m" * 900, line=3, col=1
        )
        result = script_validator.ValidationResult(valid=False, errors=(error,))

        logged = llm_client._rejection_details(result)

        assert len(logged[0]["message"]) == llm_client.MAX_LOGGED_MESSAGE_CHARS
        assert len(logged[0]["rule_id"]) <= llm_client.MAX_LOGGED_MESSAGE_CHARS

    def test_an_accepted_attempt_logs_no_rejection(self, mocker, capsys):
        _generate(mocker, [VALID_SCRIPT])

        assert _events(capsys, "generation_attempt_rejected") == []
