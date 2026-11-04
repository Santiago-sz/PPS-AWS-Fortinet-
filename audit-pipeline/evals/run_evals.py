#!/usr/bin/env python3
"""
Evals del pipeline policy-driven: normativa -> chunks -> map/reduce -> script.

Ejecuta, para cada normativa sintética de `evals/policies/*.md`, el mismo
camino que `handler_generator` recorre en producción (`chunker.chunk` ->
`llm_client.map_chunks_to_checks` -> `llm_client.generate_script_with_retries`)
y mide la calidad del resultado contra `evals/expected/<normativa>.json`.

Dos modos:
  --mode offline (default)  Sin red ni credenciales: `bedrock_client.converse`
                            se reemplaza por una función que devuelve, en
                            orden, las respuestas grabadas en
                            `evals/recorded/<normativa>.json`. Es el modo que
                            corre en CI y en `lambda/tests/test_evals_offline.py`.
  --mode live               Bedrock real (credenciales AWS en el entorno,
                            `BEDROCK_MODEL_ID` opcional). Con `--record`
                            sobrescribe las fixtures de `recorded/` con las
                            respuestas obtenidas, para poder volver a correr
                            el mismo caso offline.

Métricas por normativa (ver evals/README.md para la definición exacta):
  first_attempt_pass, attempts_used, checks_count, check_recall,
  endpoint_precision, remediation_coverage, input_tokens, output_tokens,
  latency_ms, status.

Salida: `evals/results/<timestamp>-<mode>.json` + tabla Markdown por stdout.
Código de salida 1 si alguna normativa o el agregado cae por debajo de los
umbrales de `evals/thresholds.json`.

Solo stdlib + los módulos del pipeline (se agregan a sys.path desde
`audit-pipeline/lambda`, igual que hace pytest vía pyproject.toml).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = EVALS_DIR.parent
LAMBDA_DIR = PIPELINE_DIR / "lambda"

if str(LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(LAMBDA_DIR))

import bedrock_client  # noqa: E402
import chunker  # noqa: E402
import fortigate_client  # noqa: E402
import llm_client  # noqa: E402
import script_validator  # noqa: E402

POLICIES_DIR = EVALS_DIR / "policies"
EXPECTED_DIR = EVALS_DIR / "expected"
RECORDED_DIR = EVALS_DIR / "recorded"
RESULTS_DIR = EVALS_DIR / "results"
THRESHOLDS_FILE = EVALS_DIR / "thresholds.json"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


# ---------------------------------------------------------------------------
# Entrada: normativa Markdown -> (texto, metadata) con la MISMA forma que
# devuelve extractor._extract_docx (un entry por párrafo/línea, headings con
# nivel), para que chunker.chunk detecte los límites de cláusula por
# metadata igual que con un DOCX real.
# ---------------------------------------------------------------------------


def markdown_to_text_and_metadata(markdown: str) -> tuple[str, list[dict]]:
    text_parts: list[str] = []
    metadata: list[dict] = []
    cursor = 0
    for raw_line in markdown.splitlines():
        match = _HEADING_RE.match(raw_line)
        if match:
            level = len(match.group(1))
            line = match.group(2)
            heading = line
        else:
            level = None
            line = raw_line
            heading = None
        start = cursor
        text_parts.append(line)
        cursor += len(line)
        metadata.append(
            {
                "page": None,
                "heading": heading,
                "level": level,
                "char_start": start,
                "char_end": cursor,
            }
        )
        text_parts.append("\n")
        cursor += 1
    return "".join(text_parts), metadata


def endpoint_catalog() -> list[str]:
    return [label for _, label in fortigate_client.ENDPOINTS]


# ---------------------------------------------------------------------------
# Transporte: wrapper de bedrock_client.converse que registra cada
# ConverseResult (tokens/latencia) y, en modo offline, sirve respuestas
# grabadas en orden.
# ---------------------------------------------------------------------------


def _response_text(entry: dict) -> str:
    """Una respuesta grabada puede expresarse como `text` (string crudo),
    `json` (objeto, se serializa) o `lines` (lista de líneas): las dos
    últimas existen para que las fixtures escritas a mano sean legibles."""
    if "text" in entry:
        return entry["text"]
    if "json" in entry:
        return json.dumps(entry["json"], ensure_ascii=False)
    if "lines" in entry:
        return "\n".join(entry["lines"]) + "\n"
    raise ValueError("recorded response needs one of: text, json, lines")


class Transport:
    """Context manager: mientras está activo, `bedrock_client.converse` pasa
    por acá. Clase plana (no dataclass) para poder cargarla también vía
    importlib desde los tests sin registrar el módulo en sys.modules."""

    def __init__(self, mode: str, recorded: list[dict] | None = None) -> None:
        self.mode = mode
        self.recorded: list[dict] = list(recorded or [])
        self.calls: list[bedrock_client.ConverseResult] = []
        self.captured_prompts: list[dict] = []
        self._original = bedrock_client.converse

    def __enter__(self) -> Transport:
        bedrock_client.converse = self._converse
        return self

    def __exit__(self, *exc) -> None:
        bedrock_client.converse = self._original

    def _converse(
        self, system_prompt, user_prompt, *, max_tokens, stage="unspecified", attempt=None, **kw
    ):
        self.captured_prompts.append(
            {
                "stage": stage,
                "attempt": attempt,
                "system_chars": len(system_prompt),
                "user_chars": len(user_prompt),
            }
        )
        if self.mode == "offline":
            index = len(self.calls)
            if index >= len(self.recorded):
                raise bedrock_client.BedrockCallError(
                    f"recorded fixture exhausted: call #{index + 1} ({stage}) has no response"
                )
            entry = self.recorded[index]
            result = bedrock_client.ConverseResult(
                text=_response_text(entry),
                input_tokens=int(entry.get("input_tokens", 0)),
                output_tokens=int(entry.get("output_tokens", 0)),
                cache_read_tokens=int(entry.get("cache_read_tokens", 0)),
                cache_write_tokens=int(entry.get("cache_write_tokens", 0)),
                latency_ms=float(entry.get("latency_ms", 0.0)),
                model_id=str(entry.get("model_id", "recorded")),
                stop_reason=entry.get("stop_reason", "end_turn"),
            )
        else:
            result = self._original(
                system_prompt,
                user_prompt,
                max_tokens=max_tokens,
                stage=stage,
                attempt=attempt,
                **kw,
            )
        self.calls.append(result)
        return result

    def as_recording(self) -> list[dict]:
        return [
            {
                "stage": prompt["stage"],
                "attempt": prompt["attempt"],
                "text": call.text,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "cache_read_tokens": call.cache_read_tokens,
                "cache_write_tokens": call.cache_write_tokens,
                "latency_ms": round(call.latency_ms, 1),
                "model_id": call.model_id,
                "stop_reason": call.stop_reason,
            }
            for prompt, call in zip(self.captured_prompts, self.calls, strict=False)
        ]


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    """minúsculas + sin tildes, para comparar keywords de forma tolerante."""
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _check_text(check: dict) -> str:
    clause = check.get("clause_ref") or {}
    quote = clause.get("quote") if isinstance(clause, dict) else ""
    return _fold(" ".join(str(x) for x in (check.get("title"), check.get("intent"), quote) if x))


def _keyword_groups(expected_check: dict) -> list[list[str]]:
    """Cada keyword puede ser un string o una lista de sinónimos (any-of).
    Un check producido matchea si contiene al menos un sinónimo de CADA grupo."""
    groups: list[list[str]] = []
    for item in expected_check.get("keywords", []):
        synonyms = item if isinstance(item, list) else [item]
        groups.append([_fold(s) for s in synonyms])
    return groups


def _matches(produced_text: str, groups: list[list[str]]) -> bool:
    return all(any(s in produced_text for s in group) for group in groups)


def check_recall(produced: list[dict], expected: dict) -> tuple[float, list[str], list[str]]:
    texts = [_check_text(c) for c in produced]
    matched, missed = [], []
    for exp in expected.get("checks", []):
        groups = _keyword_groups(exp)
        if groups and any(_matches(t, groups) for t in texts):
            matched.append(exp["id"])
        else:
            missed.append(exp["id"])
    total = len(matched) + len(missed)
    return (len(matched) / total if total else 1.0), matched, missed


def endpoint_precision(
    produced: list[dict], expected: dict, catalog: list[str]
) -> tuple[float, int, int]:
    allowed = set(catalog)
    expected_union: set[str] = set()
    for exp in expected.get("checks", []):
        expected_union.update(exp.get("endpoints_any", []))
    refs = [e for c in produced for e in (c.get("endpoints") or [])]
    good = [e for e in refs if e in allowed and e in expected_union]
    return (len(good) / len(refs) if refs else 0.0), len(good), len(refs)


def remediation_coverage(produced: list[dict]) -> float:
    if not produced:
        return 0.0
    covered = sum(1 for c in produced if (c.get("remediation") or {}).get("summary"))
    return covered / len(produced)


# ---------------------------------------------------------------------------
# Ejecución por normativa
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _policy_names(only: str | None) -> list[str]:
    names = sorted(p.stem for p in POLICIES_DIR.glob("*.md"))
    if only:
        names = [n for n in names if n == only]
        if not names:
            raise SystemExit(f"policy not found: {only}")
    return names


def estimate_live_tokens(text: str, attempts: int) -> int:
    """Estimación grosera (4 chars ≈ 1 token) del consumo de un run live:
    1 map (system + catálogo + texto) + hasta `attempts` reduce."""
    map_prompt = len(llm_client.MAP_SYSTEM_PROMPT) + len(text) + 400
    reduce_prompt = len(llm_client.REDUCE_SYSTEM_PROMPT) + 2500
    return (map_prompt + llm_client.MAP_MAX_TOKENS // 2) // 4 + attempts * (
        (reduce_prompt + llm_client.REDUCE_MAX_TOKENS // 2) // 4
    )


def run_policy(name: str, mode: str, max_attempts: int, verbose: bool) -> tuple[dict, Transport]:
    markdown = (POLICIES_DIR / f"{name}.md").read_text(encoding="utf-8")
    expected = _load_json(EXPECTED_DIR / f"{name}.json")
    text, metadata = markdown_to_text_and_metadata(markdown)
    chunks = chunker.chunk(text, metadata)
    catalog = endpoint_catalog()

    recorded: list[dict] = []
    if mode == "offline":
        fixture = RECORDED_DIR / f"{name}.json"
        if not fixture.exists():
            raise SystemExit(f"missing recorded fixture for offline mode: {fixture}")
        recorded = _load_json(fixture)["responses"]

    sink = io.StringIO()
    started = time.perf_counter()
    error: str | None = None
    checks: list[dict] = []
    generation: dict = {}
    with Transport(mode, recorded) as transport:
        # Los eventos JSON de observability (llm_call, generation_result, EMF)
        # salen por stdout: se capturan para no mezclarlos con la tabla.
        with contextlib.redirect_stdout(sink):
            try:
                checks = llm_client.map_chunks_to_checks(chunks, catalog)
                if checks:
                    generation = llm_client.generate_script_with_retries(
                        checks, catalog, max_attempts=max_attempts
                    )
                else:
                    generation = {"status": "no_verifiable_controls", "checks": []}
            except (
                llm_client.ClaudeCallError,
                llm_client.MapResponseParseError,
                llm_client.MapCallBudgetExceededError,
            ) as e:
                error = f"{type(e).__name__}: {e}"
                generation = {"status": "error"}
    wall_ms = (time.perf_counter() - started) * 1000.0
    if verbose and sink.getvalue():
        print(sink.getvalue(), file=sys.stderr, end="")

    status = generation.get("status", "error")
    attempts_used = int(generation.get("attempts", 0) or 0)
    script = generation.get("script")
    validation_ok = False
    if script is not None:
        validation_ok = script_validator.validate(script, {"checks": checks}).valid

    recall, matched, missed = check_recall(checks, expected)
    precision, good_refs, total_refs = endpoint_precision(checks, expected, catalog)
    min_checks = int(expected.get("min_checks", 0))
    max_checks = int(expected.get("max_checks", 10**6))

    metrics = {
        "policy": name,
        "status": status,
        "error": error,
        "chunks": len(chunks),
        "map_calls": sum(1 for p in transport.captured_prompts if p["stage"] == "map"),
        "first_attempt_pass": status == "ok" and attempts_used == 1,
        "attempts_used": attempts_used,
        "validator_ok_final": validation_ok,
        "checks_count": len(checks),
        "checks_in_range": min_checks <= len(checks) <= max_checks,
        "check_recall": round(recall, 3),
        "expected_matched": matched,
        "expected_missed": missed,
        "endpoint_precision": round(precision, 3),
        "endpoint_refs_ok": good_refs,
        "endpoint_refs_total": total_refs,
        "remediation_coverage": round(remediation_coverage(checks), 3),
        "input_tokens": sum(c.input_tokens for c in transport.calls),
        "output_tokens": sum(c.output_tokens for c in transport.calls),
        "cache_read_tokens": sum(c.cache_read_tokens for c in transport.calls),
        "latency_ms": round(sum(c.latency_ms for c in transport.calls), 1),
        "wall_ms": round(wall_ms, 1),
        "model_ids": sorted({c.model_id for c in transport.calls}),
        "produced_checks": [
            {
                "check_id": c.get("check_id"),
                "title": c.get("title"),
                "endpoints": c.get("endpoints"),
            }
            for c in checks
        ],
    }
    return metrics, transport


# ---------------------------------------------------------------------------
# Umbrales y reporte
# ---------------------------------------------------------------------------


def evaluate_thresholds(per_policy: list[dict], thresholds: dict) -> list[str]:
    failures: list[str] = []
    policy_rules = thresholds.get("per_policy", {})
    for m in per_policy:
        for metric, minimum in policy_rules.items():
            value = m.get(metric)
            if isinstance(minimum, bool):
                if bool(value) is not minimum:
                    failures.append(f"{m['policy']}: {metric}={value} (expected {minimum})")
            elif value is None or value < minimum:
                failures.append(f"{m['policy']}: {metric}={value} < {minimum}")
    overall = thresholds.get("overall", {})
    agg = aggregate(per_policy)
    for metric, minimum in overall.items():
        value = agg.get(metric)
        if value is None or value < minimum:
            failures.append(f"overall: {metric}={value} < {minimum}")
    return failures


def aggregate(per_policy: list[dict]) -> dict:
    n = len(per_policy) or 1
    return {
        "policies": len(per_policy),
        "first_attempt_pass_rate": round(
            sum(1 for m in per_policy if m["first_attempt_pass"]) / n, 3
        ),
        "generation_success_rate": round(sum(1 for m in per_policy if m["status"] == "ok") / n, 3),
        "mean_check_recall": round(sum(m["check_recall"] for m in per_policy) / n, 3),
        "mean_endpoint_precision": round(sum(m["endpoint_precision"] for m in per_policy) / n, 3),
        "mean_remediation_coverage": round(
            sum(m["remediation_coverage"] for m in per_policy) / n, 3
        ),
        "total_input_tokens": sum(m["input_tokens"] for m in per_policy),
        "total_output_tokens": sum(m["output_tokens"] for m in per_policy),
        "total_latency_ms": round(sum(m["latency_ms"] for m in per_policy), 1),
    }


def markdown_table(per_policy: list[dict], agg: dict) -> str:
    head = (
        "| policy | status | 1st-pass | attempts | checks | recall | ep-prec | remed "
        "| tok in/out | latency ms |\n"
        "|---|---|---|---|---|---|---|---|---|---|"
    )
    rows = [
        "| {policy} | {status} | {fap} | {attempts_used} | {checks_count} | {check_recall:.2f} | "
        "{endpoint_precision:.2f} | {remediation_coverage:.2f} | {input_tokens}/{output_tokens} | "
        "{latency_ms:.0f} |".format(fap="yes" if m["first_attempt_pass"] else "no", **m)
        for m in per_policy
    ]
    summary = (
        f"| **overall** | success {agg['generation_success_rate']:.2f} | "
        f"{agg['first_attempt_pass_rate']:.2f} | - | - | {agg['mean_check_recall']:.2f} | "
        f"{agg['mean_endpoint_precision']:.2f} | {agg['mean_remediation_coverage']:.2f} | "
        f"{agg['total_input_tokens']}/{agg['total_output_tokens']} | "
        f"{agg['total_latency_ms']:.0f} |"
    )
    return "\n".join([head, *rows, summary])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evals offline/live del generador de scripts")
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--policy", help="correr solo esta normativa (stem del .md)")
    parser.add_argument(
        "--record", action="store_true", help="live: guardar respuestas en recorded/"
    )
    parser.add_argument("--max-attempts", type=int, default=llm_client.MAX_GENERATION_ATTEMPTS)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_FILE)
    parser.add_argument(
        "--verbose", action="store_true", help="reenviar eventos de observability a stderr"
    )
    parser.add_argument(
        "--dump-chunks", action="store_true", help="imprimir chunk_ids/heading_path y salir"
    )
    args = parser.parse_args(argv)

    if args.record and args.mode != "live":
        parser.error("--record only makes sense with --mode live")

    names = _policy_names(args.policy)

    if args.dump_chunks:
        for name in names:
            text, metadata = markdown_to_text_and_metadata(
                (POLICIES_DIR / f"{name}.md").read_text(encoding="utf-8")
            )
            for c in chunker.chunk(text, metadata):
                print(
                    f"{name}: {c['chunk_id']} chars={len(c['text'])} "
                    f"heading_path={c['heading_path']}"
                )
        return 0

    if args.mode == "live":
        est = sum(
            estimate_live_tokens(
                (POLICIES_DIR / f"{n}.md").read_text(encoding="utf-8"), args.max_attempts
            )
            for n in names
        )
        print(
            f"[live] model={bedrock_client.resolve_model_id()} policies={len(names)} "
            f"estimated worst-case tokens ~{est} (map + {args.max_attempts} reduce attempts each)",
            file=sys.stderr,
        )

    per_policy: list[dict] = []
    for name in names:
        metrics, transport = run_policy(name, args.mode, args.max_attempts, args.verbose)
        per_policy.append(metrics)
        if args.record:
            RECORDED_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "policy": name,
                "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "model_id": bedrock_client.resolve_model_id(),
                "responses": transport.as_recording(),
            }
            (RECORDED_DIR / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    thresholds = _load_json(args.thresholds) if args.thresholds.exists() else {}
    agg = aggregate(per_policy)
    failures = evaluate_thresholds(per_policy, thresholds)

    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.results_dir / f"{stamp}-{args.mode}.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "mode": args.mode,
                "model_id": bedrock_client.resolve_model_id() if args.mode == "live" else None,
                "thresholds": thresholds,
                "overall": agg,
                "per_policy": per_policy,
                "threshold_failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"## Evals ({args.mode}) — {len(per_policy)} policies\n")
    print(markdown_table(per_policy, agg))
    print(f"\nresults: {out}")
    if failures:
        print("\nTHRESHOLD FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nall thresholds met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
