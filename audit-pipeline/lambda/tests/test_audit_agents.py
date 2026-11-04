"""Carga, enrutamiento y limites de los agentes; todo el transporte es simulado."""

import json
import logging
from dataclasses import FrozenInstanceError

import pytest

import audit_agents
import llm_client

CHUNKS = [
    {
        "chunk_id": "chunk-0001",
        "heading_path": ["Administradores"],
        "page": 1,
        "text": "Los administradores deben tener bloqueo de cuenta.",
    }
]
CHECK = {
    "title": "Bloqueo de cuenta",
    "endpoints": ["admins"],
    "severity": "high",
    "intent": "Verificar bloqueo",
    "clause_ref": {
        "chunk_id": "chunk-0001",
        "heading_path": ["Administradores"],
        "page": 1,
        "quote": CHUNKS[0]["text"],
    },
}
VALID_SCRIPT = "report.finding('chk-0001', 'indeterminate', 'Sin datos suficientes')"


def test_registry_load_is_fixed_immutable_and_does_not_call_model(mocker):
    transport = mocker.patch("llm_client._call_claude")
    agents = audit_agents.load_agents()
    assert set(agents) == {"policy_interpreter", "audit_script_generator"}
    assert llm_client.POLICY_INTERPRETER is agents["policy_interpreter"]
    assert llm_client.AUDIT_SCRIPT_GENERATOR is agents["audit_script_generator"]
    with pytest.raises(TypeError):
        agents["other"] = agents["policy_interpreter"]
    with pytest.raises(FrozenInstanceError):
        agents["policy_interpreter"].system_prompt = "replace"
    with pytest.raises(KeyError):
        _ = agents["unknown"]
    transport.assert_not_called()


def test_agent_roles_are_used_in_real_orchestration_and_retry(mocker, caplog):
    transport = mocker.patch(
        "llm_client._call_claude",
        side_effect=[
            json.dumps({"checks": [CHECK]}),
            "import os\n" + VALID_SCRIPT,
            VALID_SCRIPT,
        ],
    )
    with caplog.at_level(logging.INFO, logger="audit_agents"):
        result = llm_client.generate_audit_script(CHUNKS, ["admins"], "synthetic-key")
    assert result["status"] == "ok"
    assert result["attempts"] == 2
    calls = transport.call_args_list
    assert len(calls) == 3
    assert calls[0].args[0] == llm_client.POLICY_INTERPRETER.system_prompt
    assert calls[1].args[0] == calls[2].args[0] == llm_client.AUDIT_SCRIPT_GENERATOR.system_prompt
    assert "denied_node:Import" in calls[2].args[1]
    assert all(call.kwargs["max_tokens"] == 4096 for call in calls)
    assert "agent=policy_interpreter" in caplog.text
    assert "agent=audit_script_generator" in caplog.text
    assert "synthetic-key" not in caplog.text
    assert CHUNKS[0]["text"] not in caplog.text


@pytest.mark.parametrize(
    "response", ["[]", "null", "{}", '{"checks":null}', '{"checks":"bad"}', '{"checks":["bad"]}']
)
def test_malformed_interpretation_is_not_reported_as_no_controls(mocker, response):
    transport = mocker.patch("llm_client._call_claude", return_value=response)
    with pytest.raises(llm_client.MapResponseParseError):
        llm_client.generate_audit_script(CHUNKS, ["admins"], "synthetic-key")
    assert transport.call_count == 1


def test_registered_generator_stops_at_budget_and_never_returns_invalid_script(mocker):
    transport = mocker.patch(
        "llm_client._call_claude",
        side_effect=[
            json.dumps({"checks": [CHECK]}),
            *["import os"] * 3,
        ],
    )
    result = llm_client.generate_audit_script(CHUNKS, ["admins"], "synthetic-key")
    assert result["status"] == "generation_failed"
    assert "script" not in result
    assert transport.call_count == 1 + llm_client.AUDIT_SCRIPT_GENERATOR.default_call_budget


def test_inspection_metadata_is_safe_and_has_prompt_fingerprints():
    description = audit_agents.describe_agents()
    assert len(description) == 2
    for item in description:
        assert len(item["prompt_sha256"]) == 64
        assert item["version"] == "1.0.0"
        assert "system_prompt" not in item
        assert "api_key" not in item
    description[0]["version"] = "changed"
    assert audit_agents.describe_agents()[0]["version"] == "1.0.0"
