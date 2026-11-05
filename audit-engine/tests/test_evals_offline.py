"""
Smoke test del harness de evals en modo offline (evals/run_evals.py).

Corre `run_evals.main(["--mode", "offline", ...])` en el mismo proceso, con
las fixtures grabadas en evals/recorded/ — sin red, sin credenciales — y
verifica el contrato mínimo del runner: código de salida 0 (todos los
umbrales de evals/thresholds.json se cumplen), archivo de resultados
escrito, métricas presentes y `bedrock_client.converse` restaurado al
terminar (el runner lo monkeypatchea solo dentro de su context manager).
"""

import importlib.util
import json
from pathlib import Path

import bedrock_client

EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"
RUN_EVALS = EVALS_DIR / "run_evals.py"

REQUIRED_POLICY_METRICS = {
    "policy",
    "status",
    "first_attempt_pass",
    "attempts_used",
    "checks_count",
    "check_recall",
    "endpoint_precision",
    "remediation_coverage",
    "input_tokens",
    "output_tokens",
    "latency_ms",
}


def _load_run_evals():
    spec = importlib.util.spec_from_file_location("run_evals", RUN_EVALS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_evals_pass_thresholds_and_write_results(tmp_path, capsys):
    run_evals = _load_run_evals()
    original_converse = bedrock_client.converse

    exit_code = run_evals.main(["--mode", "offline", "--results-dir", str(tmp_path)])

    assert exit_code == 0
    assert bedrock_client.converse is original_converse  # patch undone

    results = sorted(tmp_path.glob("*-offline.json"))
    assert len(results) == 1
    payload = json.loads(results[0].read_text(encoding="utf-8"))

    assert payload["mode"] == "offline"
    assert payload["threshold_failures"] == []
    assert payload["overall"]["generation_success_rate"] == 1.0
    assert payload["overall"]["first_attempt_pass_rate"] >= 0.5

    names = {m["policy"] for m in payload["per_policy"]}
    assert names == {
        "politica-acceso-administrativo",
        "politica-contrasenas",
        "politica-registro-y-ntp",
    }
    for metrics in payload["per_policy"]:
        assert REQUIRED_POLICY_METRICS <= set(metrics)
        assert metrics["status"] == "ok"

    # The retry loop is exercised by exactly one fixture (first reduce rejected).
    by_name = {m["policy"]: m for m in payload["per_policy"]}
    assert by_name["politica-acceso-administrativo"]["first_attempt_pass"] is False
    assert by_name["politica-acceso-administrativo"]["attempts_used"] == 2
    assert by_name["politica-contrasenas"]["first_attempt_pass"] is True

    out = capsys.readouterr().out
    assert "| policy | status |" in out  # markdown table went to stdout
    assert "all thresholds met" in out


def test_offline_evals_exit_1_when_thresholds_are_not_met(tmp_path):
    run_evals = _load_run_evals()
    strict = tmp_path / "strict.json"
    strict.write_text(
        json.dumps({"per_policy": {}, "overall": {"first_attempt_pass_rate": 1.0}}),
        encoding="utf-8",
    )

    exit_code = run_evals.main(
        ["--mode", "offline", "--results-dir", str(tmp_path), "--thresholds", str(strict)]
    )

    assert exit_code == 1
    payload = json.loads(next(tmp_path.glob("*-offline.json")).read_text(encoding="utf-8"))
    assert payload["threshold_failures"] == ["overall: first_attempt_pass_rate=0.667 < 1.0"]
