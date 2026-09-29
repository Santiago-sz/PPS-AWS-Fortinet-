"""Pure presentation contracts for the existing manifest/report pair."""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import zipfile

STATUSES = {
    "pass": "Aprobado",
    "fail": "Fallido",
    "indeterminate": "Indeterminado",
    "not_applicable": "No aplicable",
    "not_evaluated": "No evaluado",
    "anomaly": "Anomalía · duplicados",
}
RUN_STATUSES = {
    "completed": "Finalizado",
    "truncated": "Parcial · límite alcanzado",
    "could_not_audit": "No se pudo auditar",
    "generation_failed": "Error de generación",
    "no_verifiable_controls": "Sin controles verificables",
    "pending": "Pendiente",
    "running": "En proceso",
}
TERMINAL = {
    "completed",
    "truncated",
    "could_not_audit",
    "generation_failed",
    "no_verifiable_controls",
}
PHASES = [
    "recibido",
    "extrayendo",
    "generando controles",
    "validando",
    "recopilando evidencia",
    "elaborando reporte",
    "finalizado",
]


def local_time(value):
    if not value:
        return "Sin datos"
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if date.tzinfo is None:
            return "Fecha sin zona horaria"
        return date.astimezone().strftime("%d/%m/%Y %H:%M %Z")
    except ValueError:
        return "Fecha inválida"


def redact(value):
    """Defense in depth; the remote service must also sanitize evidence."""
    if isinstance(value, dict):
        return {
            key: "[OCULTO]"
            if re.search(
                r"password|passwd|secret|token|api.?key|authorization|private.?key", key, re.I
            )
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)Bearer\s+[^\s,;]+", "Bearer [OCULTO]", value)
        value = re.sub(
            r"(?i)((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*)"
            r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
            r"\1[OCULTO]",
            value,
        )
        value = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[OCULTO]", value)
    return value


def section(check):
    if check.get("category"):
        return str(check["category"])
    heading = (check.get("clause_ref") or {}).get("heading_path") or []
    return (
        " / ".join(map(str, heading))
        if isinstance(heading, list) and heading
        else (str(heading) if heading else "Sin sección")
    )


def normalize(manifest, report, context=None):
    """One metric slot per unique expected check; duplicates never silently win.

    All observations are retained. A duplicated expected ID or finding is an
    anomaly excluded from coverage and compliance; unknown checks are retained
    outside the expected universe. Incomplete universes suppress total posture.
    """
    if not isinstance(manifest, dict) or not isinstance(report, dict):
        raise ValueError("Manifest y reporte deben ser objetos JSON.")
    if not report.get("run_id") or manifest.get("run_id") != report["run_id"]:
        raise ValueError("El manifest y el reporte deben pertenecer al mismo run_id.")
    if (
        manifest.get("policy_key")
        and report.get("policy_key")
        and manifest["policy_key"] != report["policy_key"]
    ):
        raise ValueError("La política del manifest no coincide con el reporte.")
    checks, findings = manifest.get("checks", []), report.get("findings", [])
    if not isinstance(checks, list) or not isinstance(findings, list):
        raise ValueError("checks y findings deben ser listas.")
    if any(
        not isinstance(c, dict) or not isinstance(c.get("check_id"), str) or not c["check_id"]
        for c in checks + findings
    ):
        raise ValueError("Cada control y hallazgo necesita un check_id válido.")
    expected = Counter(c["check_id"] for c in checks)
    observed = defaultdict(list)
    for finding in findings:
        observed[finding["check_id"]].append(deepcopy(finding))
    rows, counts, groups = [], Counter(), defaultdict(Counter)
    seen = set()
    anomalies = []
    for check in checks:
        cid = check["check_id"]
        if cid in seen:
            continue
        seen.add(cid)
        entries = observed[cid]
        result = entries[0].get("status") if len(entries) == 1 else "not_evaluated"
        if expected[cid] > 1 or len(entries) > 1:
            result = "anomaly"
            anomalies.append(f"{cid}: controles u observaciones duplicados")
        elif result not in STATUSES or result == "anomaly":
            result = "indeterminate"
            anomalies.append(f"{cid}: estado de resultado desconocido")
        counts[result] += 1
        group = section(check)
        groups[group][result] += 1
        finding = entries[0] if len(entries) == 1 else {}
        clause = finding.get("clause_ref") or {}
        traceable = bool(
            finding.get("traceable")
            and isinstance(clause, dict)
            and isinstance(clause.get("quote"), str)
            and clause["quote"].strip()
        )
        rows.append(
            {
                "check_id": cid,
                "title": check.get("title", cid),
                "status": result,
                "section": group,
                "intent": check.get("intent", "Sin criterio informado"),
                "evidence": redact(finding.get("evidence", "Sin evidencia registrada")),
                "traceable": traceable,
                "clause_ref": clause if traceable else None,
                "endpoints_used": finding.get("endpoints_used", []),
                "expected_endpoints": check.get("endpoints", []),
                "observations": redact(entries),
                "finding_id": finding.get("id"),
                "definitions": redact([c for c in checks if c["check_id"] == cid]),
                "follow_up": finding.get("follow_up", {}),
            }
        )
    unknown = [redact(f) for f in findings if f["check_id"] not in expected]
    if unknown:
        anomalies.append(f"{len(unknown)} observaciones fuera del manifest")
    total = len(expected)
    evaluated = sum(counts[s] for s in ("pass", "fail", "indeterminate", "not_applicable"))
    applicable = counts["pass"] + counts["fail"]
    partial = (
        report.get("status") != "completed"
        or bool(report.get("truncated"))
        or evaluated != total
        or bool(anomalies)
    )
    return {
        **(context or {}),
        "run_id": report["run_id"],
        "status": report.get("status", "unknown"),
        "timestamp": report.get("timestamp"),
        "policy_sha256": manifest.get("policy_sha256"),
        "counts": {
            **{key: counts[key] for key in STATUSES},
            "expected": total,
            "evaluated": evaluated,
        },
        "coverage_percent": 100 * evaluated / total if total else None,
        "compliance_percent": 100 * counts["pass"] / applicable if applicable else None,
        "partial": partial,
        "rows": rows,
        "groups": dict(groups),
        "anomalies": anomalies,
        "unknown_findings": unknown,
        "failure_reason": redact(report.get("failure_reason") or ""),
    }


def load_pair(manifest_path, report_path):
    paths = [Path(manifest_path), Path(report_path)]
    if any(p.stat().st_size > 20 * 1024 * 1024 for p in paths):
        raise ValueError("Cada archivo JSON debe ocupar menos de 20 MB.")
    manifest, report = [json.loads(p.read_text(encoding="utf-8-sig")) for p in paths]
    # Only retain GUI fields. In particular, never load/render a generated script.
    result = normalize(
        manifest,
        report,
        {
            "source": "import",
            "policy_name": "Reporte importado",
            "policy_version": "No informada",
            "device": {"name": "No informado"},
        },
    )
    return result


def inspect_policy(path, max_bytes):
    path = Path(path)
    mime_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    suffix = path.suffix.lower()
    if suffix not in mime_types:
        raise ValueError("Seleccioná un documento PDF o DOCX.")
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise ValueError(f"El archivo debe ocupar entre 1 byte y {max_bytes / 1048576:g} MB.")
    data = path.read_bytes()
    if len(data) != size or len(data) > max_bytes:
        raise ValueError("El archivo cambió durante la lectura. Seleccionalo nuevamente.")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("No se pudo extraer texto: cabecera PDF inválida.")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                if not {"[Content_Types].xml", "word/document.xml"} <= set(archive.namelist()):
                    raise ValueError("No se pudo extraer texto: DOCX inválido.")
        except zipfile.BadZipFile as exc:
            raise ValueError("No se pudo extraer texto: DOCX corrupto.") from exc
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": size,
        "mime_type": mime_types[suffix],
        "extension": suffix[1:],
        "data": data,
    }


def export_local(result, fmt):
    safe = redact(result)
    if fmt == "json":
        return json.dumps(safe, ensure_ascii=False, indent=2).encode("utf-8")
    lines = [
        "# PPS · Vista local de auditoría",
        "",
        f"Origen: {safe.get('source', 'caché')} · Run: {safe['run_id']}",
        f"Estado: {safe['status']} · Fecha UTC: {safe.get('timestamp')}",
        "Parcial / no confiable como postura total" if safe["partial"] else "",
        "",
        "```json",
        json.dumps(safe, ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines).encode("utf-8")
