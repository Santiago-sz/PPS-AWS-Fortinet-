"""
Tests de la evaluación de calidad de recuperación (`evals/run_evals.py
--suite retrieval`, lógica en `evals/retrieval_eval.py`).

El modo offline puntúa las fixtures grabadas (sintéticas hasta que exista un
corpus real). El modo live se prueba con `knowledge_retriever.retrieve`
reemplazado: nunca se llama a AWS.
"""

import importlib.util
import json
from pathlib import Path

import pytest

import knowledge_retriever

EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"
RUN_EVALS = EVALS_DIR / "run_evals.py"
REQUIRED_TOPICS = {
    "admin_access",
    "password_policy",
    "logging",
    "ntp",
    "firewall_policy",
    "ssl_inspection",
}


def _load_run_evals():
    spec = importlib.util.spec_from_file_location("run_evals", RUN_EVALS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_evals():
    return _load_run_evals()


@pytest.fixture
def retrieval_eval(run_evals):
    return run_evals.retrieval_eval


class TestMetrics:
    def test_first_hit_rank_matches_substrings_case_insensitively_within_k(self, retrieval_eval):
        sources = ["s3://kb/otro.pdf", None, "s3://kb/FortiOS-Hardening-Guide.pdf"]

        assert retrieval_eval.first_hit_rank(sources, ["hardening"], k=5) == 3
        assert retrieval_eval.first_hit_rank(sources, ["hardening"], k=2) is None
        assert retrieval_eval.first_hit_rank(sources, ["cli-reference", "otro"], k=5) == 1
        assert retrieval_eval.first_hit_rank([], ["hardening"], k=5) is None

    def test_hit_rate_and_mean_reciprocal_rank(self, retrieval_eval):
        per_question = [
            {"id": "a", "hit": True, "rank": 1, "reciprocal_rank": 1.0},
            {"id": "b", "hit": True, "rank": 2, "reciprocal_rank": 0.5},
            {"id": "c", "hit": True, "rank": 4, "reciprocal_rank": 0.25},
            {"id": "d", "hit": False, "rank": None, "reciprocal_rank": 0.0},
        ]

        aggregate = retrieval_eval.aggregate(per_question, k=5)

        assert aggregate == {"questions": 4, "k": 5, "hit_rate_at_k": 0.75, "mrr": 0.438}

    def test_thresholds_report_each_metric_below_its_minimum(self, retrieval_eval):
        aggregate = {"questions": 4, "k": 5, "hit_rate_at_k": 0.75, "mrr": 0.438}

        assert retrieval_eval.evaluate_thresholds(aggregate, {"hit_rate_at_k": 0.7}) == []
        assert retrieval_eval.evaluate_thresholds(
            aggregate, {"hit_rate_at_k": 0.8, "mrr": 0.6}
        ) == ["retrieval: hit_rate_at_k=0.75 < 0.8", "retrieval: mrr=0.438 < 0.6"]


class TestQuestionSet:
    def test_question_set_is_versioned_and_well_formed(self, retrieval_eval):
        data = json.loads(retrieval_eval.QUESTIONS_FILE.read_text(encoding="utf-8"))

        assert isinstance(data["version"], int)
        assert isinstance(data["k"], int) and 1 <= data["k"] <= knowledge_retriever.MAX_RESULTS
        ids = [q["id"] for q in data["questions"]]
        assert len(ids) == len(set(ids)) >= 12
        for question in data["questions"]:
            assert question["question"].strip()
            assert question["expected_sources"], question["id"]
            assert all(isinstance(s, str) and s.strip() for s in question["expected_sources"])
        assert {q["topic"] for q in data["questions"]} == REQUIRED_TOPICS

    def test_recorded_fixture_is_marked_synthetic_and_has_no_fragment_text(self, retrieval_eval):
        recorded = json.loads(retrieval_eval.RECORDED_FILE.read_text(encoding="utf-8"))
        questions = json.loads(retrieval_eval.QUESTIONS_FILE.read_text(encoding="utf-8"))

        assert recorded["synthetic"] is True
        assert recorded["questions_version"] == questions["version"]
        assert set(recorded["results"]) == {q["id"] for q in questions["questions"]}
        for ranked in recorded["results"].values():
            for entry in ranked:
                assert set(entry) == {"source", "score"}


class TestOfflineSuite:
    def test_offline_retrieval_suite_passes_thresholds_and_writes_results(
        self, run_evals, tmp_path, capsys
    ):
        exit_code = run_evals.main(
            ["--suite", "retrieval", "--mode", "offline", "--results-dir", str(tmp_path)]
        )

        assert exit_code == 0
        results = sorted(tmp_path.glob("*-retrieval-offline.json"))
        assert len(results) == 1
        payload = json.loads(results[0].read_text(encoding="utf-8"))
        assert payload["suite"] == "retrieval"
        assert payload["mode"] == "offline"
        assert payload["synthetic_fixture"] is True
        assert payload["threshold_failures"] == []
        assert 0.0 < payload["overall"]["mrr"] < 1.0
        assert payload["overall"]["hit_rate_at_k"] >= 0.8
        assert len(payload["per_question"]) == payload["overall"]["questions"]
        out = capsys.readouterr().out
        assert "| question | topic |" in out
        assert "SYNTHETIC" in out
        assert "all thresholds met" in out

    def test_offline_retrieval_suite_exits_1_below_thresholds(self, run_evals, tmp_path):
        strict = tmp_path / "strict.json"
        strict.write_text(json.dumps({"retrieval": {"mrr": 1.0}}), encoding="utf-8")

        exit_code = run_evals.main(
            [
                "--suite",
                "retrieval",
                "--results-dir",
                str(tmp_path),
                "--thresholds",
                str(strict),
            ]
        )

        assert exit_code == 1
        payload = json.loads(
            next(tmp_path.glob("*-retrieval-offline.json")).read_text(encoding="utf-8")
        )
        assert len(payload["threshold_failures"]) == 1
        assert payload["threshold_failures"][0].startswith("retrieval: mrr=")

    def test_default_suite_is_still_the_generation_evals(self, run_evals, tmp_path, capsys):
        exit_code = run_evals.main(["--mode", "offline", "--results-dir", str(tmp_path)])

        assert exit_code == 0
        assert [p.name.split("-", 1)[1] for p in tmp_path.glob("*.json")] == ["offline.json"]
        assert "| policy | status |" in capsys.readouterr().out


class TestLiveSuite:
    def test_live_mode_queries_the_knowledge_base_through_the_retriever(
        self, run_evals, retrieval_eval, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KBTEST0001")
        monkeypatch.setenv("KNOWLEDGE_BASE_FORTIOS_VERSION", "7.4")
        recorded_file = tmp_path / "recorded.json"
        monkeypatch.setattr(retrieval_eval, "RECORDED_FILE", recorded_file)
        calls = []

        def fake_retrieve(query, *, knowledge_base_id, max_results, metadata_filter=None):
            calls.append((query, knowledge_base_id, max_results, metadata_filter))
            return [
                knowledge_retriever.RetrievedFragment(
                    text="texto-recuperado",
                    source_uri=(
                        "https://pps-prod-knowledge-123456789012.s3.amazonaws.com/"
                        "fortinet/fortios-hardening.pdf"
                    ),
                    score=0.8,
                )
            ]

        monkeypatch.setattr(knowledge_retriever, "retrieve", fake_retrieve)
        questions = json.loads(retrieval_eval.QUESTIONS_FILE.read_text(encoding="utf-8"))

        run_evals.main(
            [
                "--suite",
                "retrieval",
                "--mode",
                "live",
                "--record",
                "--results-dir",
                str(tmp_path / "results"),
            ]
        )

        assert [c[0] for c in calls] == [q["question"] for q in questions["questions"]]
        assert {c[1] for c in calls} == {"KBTEST0001"}
        assert {c[2] for c in calls} == {questions["k"]}
        assert calls[0][3] == {"equals": {"key": "fortios_version", "value": "7.4"}}
        recorded = json.loads(recorded_file.read_text(encoding="utf-8"))
        assert recorded["synthetic"] is False
        assert recorded["questions_version"] == questions["version"]
        assert "texto-recuperado" not in recorded_file.read_text(encoding="utf-8")
        assert "123456789012" not in recorded_file.read_text(encoding="utf-8")
        first = next(iter(recorded["results"].values()))
        assert first == [{"source": "fortinet/fortios-hardening.pdf", "score": 0.8}]
        payload = json.loads(
            next((tmp_path / "results").glob("*-retrieval-live.json")).read_text(encoding="utf-8")
        )
        assert payload["synthetic_fixture"] is False
        assert "123456789012" not in json.dumps(payload)
        assert "SYNTHETIC" not in capsys.readouterr().out

    def test_live_mode_requires_a_configured_knowledge_base(self, run_evals, tmp_path, monkeypatch):
        monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)

        with pytest.raises(SystemExit) as exc:
            run_evals.main(
                ["--suite", "retrieval", "--mode", "live", "--results-dir", str(tmp_path)]
            )

        assert "KNOWLEDGE_BASE_ID" in str(exc.value)

    def test_live_retrieval_error_scores_the_question_as_a_miss(
        self, run_evals, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KBTEST0001")
        monkeypatch.delenv("KNOWLEDGE_BASE_FORTIOS_VERSION", raising=False)

        def failing_retrieve(query, **kwargs):
            raise knowledge_retriever.KnowledgeRetrievalError("ThrottlingException")

        monkeypatch.setattr(knowledge_retriever, "retrieve", failing_retrieve)

        exit_code = run_evals.main(
            ["--suite", "retrieval", "--mode", "live", "--results-dir", str(tmp_path)]
        )

        assert exit_code == 1
        payload = json.loads(
            next(tmp_path.glob("*-retrieval-live.json")).read_text(encoding="utf-8")
        )
        assert payload["overall"]["hit_rate_at_k"] == 0.0
        assert {q["error"] for q in payload["per_question"]} == {"ThrottlingException"}
