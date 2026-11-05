"""
Tests para llm_client.py — fase map (chunk group -> PolicyCheck[]) y fase
reduce (PolicyCheck[] -> script.py), con ciclo de reintento acotado.

Mockea el cliente `bedrock-runtime` (via `bedrock_client.get_client`) —
nunca se llama a Amazon Bedrock real. Cada test puede inspeccionar las
requests Converse capturadas (`messages[0].content[0].text` es el prompt
de usuario enviado).
"""

import json

import pytest
from botocore.exceptions import ClientError

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
