"""
Tests para llm_client.py — fase map (chunk group -> PolicyCheck[]) y fase
reduce (PolicyCheck[] -> script.py), con ciclo de reintento acotado.

Mockea la llamada HTTP a la API de Claude (urllib.request.urlopen) —
nunca se llama a la API real de Anthropic (ver analyzer.py/test_analyzer.py
por el patrón).
"""

import json

import pytest

import script_validator
from llm_client import (
    MAX_GENERATION_ATTEMPTS,
    MAX_MAP_CALLS,
    MapCallBudgetExceededError,
    build_retry_feedback,
    generate_audit_script,
    group_chunks_for_map,
    map_chunks_to_checks,
)

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


def _fake_response(body: bytes):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return body

    return _Resp()


def _claude_text_response_body(text: str) -> bytes:
    """Simula el body JSON crudo que devuelve la API de Claude, con `text`
    como contenido literal de response.content[0].text (JSON o código Python,
    según lo que se esté testeando)."""
    payload = {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 500, "output_tokens": 200},
    }
    return json.dumps(payload).encode("utf-8")


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
            "intent": "Verify admin lockout is enabled",
        }
    ]
}

EMPTY_MAP_RESPONSE = {"checks": []}


class TestGroupChunksForMap:
    """Agrupación pura de chunks en grupos para cada llamada de map —
    sin llamadas HTTP, sin mocks."""

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


class TestMapCallBudget:
    def test_map_call_budget_exceeded_fails_explicitly_before_any_http_call(self, mocker):
        # 20 chunks of 600 chars each with a tiny per-group budget forces > MAX_MAP_CALLS groups
        chunks = [_make_chunk(f"chunk-{i:04d}", "x" * 600) for i in range(20)]
        urlopen = mocker.patch("llm_client.urllib.request.urlopen")

        with pytest.raises(MapCallBudgetExceededError):
            map_chunks_to_checks(
                chunks,
                ENDPOINT_CATALOG,
                claude_api_key="sk-ant-dummy",
                max_map_calls=2,
                max_group_chars=1_000,
            )

        # explicit failure BEFORE any API call — never silently truncate to fit
        urlopen.assert_not_called()

    def test_default_max_map_calls_constant_is_twelve(self):
        assert MAX_MAP_CALLS == 12


class TestMapChunksToChecks:
    def test_map_produces_policy_checks_with_assigned_check_ids(self, mocker):
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        mocker.patch(
            "llm_client.urllib.request.urlopen",
            return_value=_fake_response(
                _claude_text_response_body(json.dumps(ONE_CHECK_MAP_RESPONSE))
            ),
        )

        checks = map_chunks_to_checks(chunks, ENDPOINT_CATALOG, claude_api_key="sk-ant-dummy")

        assert len(checks) == 1
        assert checks[0]["check_id"] == "chk-0001"
        assert checks[0]["title"] == "Admin lockout enabled"
        assert checks[0]["clause_ref"]["chunk_id"] == "chunk-0001"
        assert checks[0]["endpoints"] == ["admins"]

    def test_map_does_not_truncate_large_chunk_text_in_the_request(self, mocker):
        large_text = "Articulo largo. " * 2000  # well over any legacy MAX_DATA_CHARS-style limit
        chunks = [_make_chunk("chunk-0001", large_text)]
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _fake_response(_claude_text_response_body(json.dumps(EMPTY_MAP_RESPONSE)))

        mocker.patch("llm_client.urllib.request.urlopen", side_effect=fake_urlopen)

        map_chunks_to_checks(chunks, ENDPOINT_CATALOG, claude_api_key="sk-ant-dummy")

        sent_prompt = captured["body"]["messages"][0]["content"]
        assert large_text in sent_prompt
        assert "truncad" not in sent_prompt.lower()


class TestBuildRetryFeedback:
    """Feedback puro derivado de un ValidationResult — sin llamadas HTTP."""

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


class TestGenerateAuditScriptStandard:
    def test_standard_generation_produces_a_read_only_valid_script(self, mocker):
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        responses = [
            _fake_response(_claude_text_response_body(json.dumps(ONE_CHECK_MAP_RESPONSE))),
            _fake_response(_claude_text_response_body(VALID_SCRIPT)),
        ]
        mocker.patch("llm_client.urllib.request.urlopen", side_effect=responses)

        result = generate_audit_script(chunks, ENDPOINT_CATALOG, claude_api_key="sk-ant-dummy")

        assert result["status"] == "ok"
        assert result["attempts"] == 1
        assert "fgt.get(" in result["script"]
        assert "report.finding(" in result["script"]
        # never a write/delete/config-changing call — read-only by construction,
        # confirmed by re-running the same validator the sandbox would use
        validation = script_validator.validate(result["script"], {"checks": result["checks"]})
        assert validation.valid


class TestGenerateAuditScriptRetry:
    def test_invalid_script_triggers_exactly_one_retry_with_correct_feedback(self, mocker):
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        captured_bodies = []
        responses = [
            _fake_response(_claude_text_response_body(json.dumps(ONE_CHECK_MAP_RESPONSE))),
            _fake_response(_claude_text_response_body(INVALID_SCRIPT_BAD_IMPORT)),
            _fake_response(_claude_text_response_body(VALID_SCRIPT)),
        ]

        def fake_urlopen(req, timeout=None):
            captured_bodies.append(json.loads(req.data.decode("utf-8")))
            return responses[len(captured_bodies) - 1]

        mocker.patch("llm_client.urllib.request.urlopen", side_effect=fake_urlopen)

        result = generate_audit_script(chunks, ENDPOINT_CATALOG, claude_api_key="sk-ant-dummy")

        assert result["status"] == "ok"
        assert result["attempts"] == 2

        # 3 HTTP calls total: 1 map + 2 reduce (1 initial + 1 retry)
        assert len(captured_bodies) == 3
        retry_prompt = captured_bodies[2]["messages"][0]["content"]
        assert "denied_node:Import" in retry_prompt
        assert "intento 1" in retry_prompt  # feedback references the failed attempt
        assert "import os" in retry_prompt  # previous script included verbatim

    def test_retry_budget_exhausted_after_three_attempts_returns_generation_failed(self, mocker):
        chunks = [_make_chunk("chunk-0001", "Los administradores deben tener bloqueo.")]
        responses = [
            _fake_response(_claude_text_response_body(json.dumps(ONE_CHECK_MAP_RESPONSE))),
            _fake_response(_claude_text_response_body(INVALID_SCRIPT_BAD_IMPORT)),
            _fake_response(_claude_text_response_body(INVALID_SCRIPT_BAD_IMPORT)),
            _fake_response(_claude_text_response_body(INVALID_SCRIPT_BAD_IMPORT)),
        ]
        mocker.patch("llm_client.urllib.request.urlopen", side_effect=responses)

        result = generate_audit_script(chunks, ENDPOINT_CATALOG, claude_api_key="sk-ant-dummy")

        assert result["status"] == "generation_failed"
        assert result["attempts"] == MAX_GENERATION_ATTEMPTS
        assert result["errors"][0]["rule_id"] == "denied_node:Import"
        # never executed / never returned as a usable script
        assert "script" not in result


class TestGenerateAuditScriptNoVerifiableControls:
    def test_empty_policy_checks_reports_no_verifiable_controls_without_calling_reduce(
        self, mocker
    ):
        chunks = [_make_chunk("chunk-0001", "Texto sin controles FortiGate-verificables.")]
        urlopen = mocker.patch(
            "llm_client.urllib.request.urlopen",
            return_value=_fake_response(_claude_text_response_body(json.dumps(EMPTY_MAP_RESPONSE))),
        )

        result = generate_audit_script(chunks, ENDPOINT_CATALOG, claude_api_key="sk-ant-dummy")

        assert result["status"] == "no_verifiable_controls"
        assert result["checks"] == []
        # exactly one HTTP call (the map call) — reduce is never invoked
        assert urlopen.call_count == 1
