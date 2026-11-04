"""
Tests para observability.py — eventos JSON, metricas EMF y timer.

Capturan stdout (el handler del modulo escribe ahi, sin propagar al root
logger) y parsean cada linea como JSON para validar la estructura.
"""

import json
import logging
import time

import observability


def _json_lines(captured: str) -> list[dict]:
    lines = [line for line in captured.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


class TestLogEvent:
    def test_emits_exactly_one_json_line_with_event_and_timestamp(self, capsys):
        observability.log_event("llm_call", stage="map", input_tokens=12)

        parsed = _json_lines(capsys.readouterr().out)

        assert len(parsed) == 1
        payload = parsed[0]
        assert payload["event"] == "llm_call"
        assert payload["stage"] == "map"
        assert payload["input_tokens"] == 12
        assert payload["ts"].endswith("Z")
        assert "T" in payload["ts"]

    def test_non_serializable_fields_are_stringified_not_crashing(self, capsys):
        observability.log_event("x", when=object())

        parsed = _json_lines(capsys.readouterr().out)
        assert len(parsed) == 1
        assert isinstance(parsed[0]["when"], str)

    def test_does_not_propagate_to_root_logger(self, caplog):
        # If it propagated, the root handler (with the Lambda log format)
        # would print a second, non-JSON copy of the line.
        with caplog.at_level(logging.INFO):
            observability.log_event("quiet")
        assert not any("quiet" in rec.getMessage() for rec in caplog.records)


class TestEmitMetric:
    def test_emits_valid_emf_structure(self, capsys):
        observability.emit_metric("LlmInputTokens", 1500, dimensions={"Stage": "map"})

        parsed = _json_lines(capsys.readouterr().out)
        assert len(parsed) == 1
        payload = parsed[0]

        aws = payload["_aws"]
        assert isinstance(aws["Timestamp"], int)
        metric_block = aws["CloudWatchMetrics"][0]
        assert metric_block["Namespace"] == "PPS/AuditPipeline"
        assert metric_block["Dimensions"] == [["Stage"]]
        assert metric_block["Metrics"] == [{"Name": "LlmInputTokens", "Unit": "Count"}]
        # EMF requires the metric value and dimension values as top-level fields
        assert payload["LlmInputTokens"] == 1500
        assert payload["Stage"] == "map"

    def test_no_dimensions_yields_empty_dimension_set(self, capsys):
        observability.emit_metric("GenerationAttempts", 2)

        payload = _json_lines(capsys.readouterr().out)[0]
        assert payload["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]
        assert payload["GenerationAttempts"] == 2

    def test_custom_unit_and_namespace(self, capsys):
        observability.emit_metric("LlmLatencyMs", 812.5, unit="Milliseconds", namespace="X/Y")

        payload = _json_lines(capsys.readouterr().out)[0]
        block = payload["_aws"]["CloudWatchMetrics"][0]
        assert block["Namespace"] == "X/Y"
        assert block["Metrics"][0]["Unit"] == "Milliseconds"
        assert payload["LlmLatencyMs"] == 812.5


class TestTimer:
    def test_timer_measures_elapsed_milliseconds(self):
        with observability.timer() as t:
            time.sleep(0.02)

        assert t.elapsed_ms >= 15
        # frozen after exiting the context
        frozen = t.elapsed_ms
        time.sleep(0.005)
        assert t.elapsed_ms == frozen

    def test_timer_is_live_while_running(self):
        t = observability.Timer()
        first = t.elapsed_ms
        time.sleep(0.005)
        assert t.elapsed_ms > first
