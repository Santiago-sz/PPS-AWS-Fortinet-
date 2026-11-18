"""
Evals de calidad de recuperación de la Knowledge Base (suite `retrieval` de
`run_evals.py`).

Mide si, para cada pregunta de `retrieval/questions.json`, la Knowledge Base
devuelve entre los primeros `k` resultados algún documento esperado. No
invoca al modelo ni genera scripts: evalúa solo la operación `Retrieve`.

Dos modos, con la misma convención que la suite de generación:
  offline  Sin red ni credenciales: puntúa los resultados grabados en
           `retrieval/recorded.json`. Mientras no exista un corpus real esa
           fixture es SINTÉTICA (`"synthetic": true`): ejercita el cálculo de
           métricas y umbrales, no la calidad de una base real.
  live     Consulta la base configurada en `KNOWLEDGE_BASE_ID` a través de
           `knowledge_retriever.retrieve` (credenciales AWS en el entorno;
           `KNOWLEDGE_BASE_FORTIOS_VERSION` opcional). Con `--record`
           sobrescribe la fixture con los orígenes y puntajes obtenidos; el
           texto de los fragmentos nunca se guarda.

Métricas (ver evals/README.md):
  hit_rate_at_k  Fracción de preguntas con algún documento esperado entre los
                 primeros k resultados.
  mrr            Media del recíproco de la posición del primer documento
                 esperado (0 si no aparece entre los primeros k).

Solo stdlib + `knowledge_retriever`.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = EVALS_DIR.parent
for area in ("generator", "contracts"):
    if str(PIPELINE_DIR / area) not in sys.path:
        sys.path.insert(0, str(PIPELINE_DIR / area))

import knowledge_retriever  # noqa: E402

RETRIEVAL_DIR = EVALS_DIR / "retrieval"
QUESTIONS_FILE = RETRIEVAL_DIR / "questions.json"
RECORDED_FILE = RETRIEVAL_DIR / "recorded.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


def first_hit_rank(sources: list[str | None], expected: list[str], k: int) -> int | None:
    """Posición (desde 1) del primer origen, entre los primeros `k`, que
    contiene alguno de los identificadores esperados (subcadena, sin
    distinguir mayúsculas). None si ninguno coincide."""
    wanted = [e.lower() for e in expected]
    for rank, source in enumerate(sources[:k], start=1):
        if source and any(w in source.lower() for w in wanted):
            return rank
    return None


def score_question(question: dict, ranked: list[dict], k: int, error: str | None = None) -> dict:
    rank = first_hit_rank([r.get("source") for r in ranked], question["expected_sources"], k)
    return {
        "id": question["id"],
        "topic": question.get("topic"),
        "hit": rank is not None,
        "rank": rank,
        "reciprocal_rank": round(1.0 / rank, 3) if rank else 0.0,
        "results": ranked[:k],
        "error": error,
    }


def aggregate(per_question: list[dict], k: int) -> dict:
    n = len(per_question) or 1
    return {
        "questions": len(per_question),
        "k": k,
        "hit_rate_at_k": round(sum(1 for q in per_question if q["hit"]) / n, 3),
        "mrr": round(sum(q["reciprocal_rank"] for q in per_question) / n, 3),
    }


def evaluate_thresholds(agg: dict, thresholds: dict) -> list[str]:
    failures: list[str] = []
    for metric, minimum in thresholds.items():
        value = agg.get(metric)
        if value is None or value < minimum:
            failures.append(f"retrieval: {metric}={value} < {minimum}")
    return failures


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------


def _ranked_offline(questions: list[dict], recorded: dict) -> dict[str, tuple[list[dict], None]]:
    results = recorded.get("results", {})
    return {q["id"]: (list(results.get(q["id"], [])), None) for q in questions}


def _ranked_live(
    questions: list[dict], k: int, config: knowledge_retriever.RetrievalConfig, verbose: bool
) -> dict[str, tuple[list[dict], str | None]]:
    ranked: dict[str, tuple[list[dict], str | None]] = {}
    sink = io.StringIO()
    # Los eventos `kb_retrieve` salen por stdout: se capturan para no
    # mezclarlos con la tabla.
    with contextlib.redirect_stdout(sink):
        for question in questions:
            try:
                fragments = knowledge_retriever.retrieve(
                    question["question"],
                    knowledge_base_id=config.knowledge_base_id,
                    max_results=k,
                    metadata_filter=config.metadata_filter,
                )
            except knowledge_retriever.KnowledgeRetrievalError as e:
                ranked[question["id"]] = ([], str(e))
                continue
            ranked[question["id"]] = (
                [
                    {
                        # Solo la clave del objeto: el bucket incluye el id de cuenta.
                        "source": knowledge_retriever.source_identifier(f.source_uri),
                        "score": round(f.score, 4) if f.score is not None else None,
                    }
                    for f in fragments
                ],
                None,
            )
    if verbose and sink.getvalue():
        print(sink.getvalue(), file=sys.stderr, end="")
    return ranked


def markdown_table(per_question: list[dict], agg: dict) -> str:
    head = "| question | topic | hit | rank | rr | top source |\n|---|---|---|---|---|---|"
    rows = []
    for q in per_question:
        top = q["results"][0].get("source") if q["results"] else None
        rows.append(
            f"| {q['id']} | {q['topic']} | {'yes' if q['hit'] else 'no'} | "
            f"{q['rank'] if q['rank'] else '-'} | {q['reciprocal_rank']:.2f} | "
            f"{top or q['error'] or '-'} |"
        )
    summary = (
        f"| **overall** | {agg['questions']} questions | hit@{agg['k']} "
        f"{agg['hit_rate_at_k']:.2f} | - | mrr {agg['mrr']:.2f} | - |"
    )
    return "\n".join([head, *rows, summary])


def run_suite(
    *, mode: str, record: bool, results_dir: Path, thresholds_file: Path, verbose: bool = False
) -> int:
    """Corre la suite y devuelve el código de salida (1 si no se cumplen los
    umbrales de la clave `retrieval` del archivo de umbrales)."""
    question_set = _load_json(QUESTIONS_FILE)
    questions = question_set["questions"]
    k = int(question_set["k"])

    knowledge_base_id = None
    if mode == "live":
        config = knowledge_retriever.load_config()
        if not config.enabled:
            raise SystemExit(
                f"{knowledge_retriever.KNOWLEDGE_BASE_ID_ENV} is required for "
                "--suite retrieval --mode live"
            )
        knowledge_base_id = config.knowledge_base_id
        print(
            f"[live] knowledge_base={knowledge_base_id} questions={len(questions)} k={k} "
            f"filter={config.metadata_filter}",
            file=sys.stderr,
        )
        ranked = _ranked_live(questions, k, config, verbose)
        synthetic = False
    else:
        if not RECORDED_FILE.exists():
            raise SystemExit(f"missing recorded fixture for offline mode: {RECORDED_FILE}")
        recorded = _load_json(RECORDED_FILE)
        ranked = _ranked_offline(questions, recorded)
        synthetic = bool(recorded.get("synthetic"))

    per_question = [
        score_question(q, ranked[q["id"]][0], k, error=ranked[q["id"]][1]) for q in questions
    ]

    if record:
        RECORDED_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECORDED_FILE.write_text(
            json.dumps(
                {
                    "synthetic": False,
                    "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "knowledge_base_id": knowledge_base_id,
                    "questions_version": question_set["version"],
                    "k": k,
                    "results": {q["id"]: ranked[q["id"]][0] for q in questions},
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    all_thresholds = _load_json(thresholds_file) if thresholds_file.exists() else {}
    thresholds = all_thresholds.get("retrieval", {})
    agg = aggregate(per_question, k)
    failures = evaluate_thresholds(agg, thresholds)

    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = results_dir / f"{stamp}-retrieval-{mode}.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "suite": "retrieval",
                "mode": mode,
                "synthetic_fixture": synthetic,
                "knowledge_base_id": knowledge_base_id,
                "questions_version": question_set["version"],
                "thresholds": thresholds,
                "overall": agg,
                "per_question": per_question,
                "threshold_failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"## Retrieval evals ({mode}) — {len(per_question)} questions, k={k}\n")
    if synthetic:
        print(
            "SYNTHETIC fixture: these results exercise the metrics, "
            "not the quality of a real knowledge base.\n"
        )
    print(markdown_table(per_question, agg))
    print(f"\nresults: {out}")
    if failures:
        print("\nTHRESHOLD FAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nall thresholds met")
    return 0
