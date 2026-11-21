#!/usr/bin/env python3
"""
Local runner for the executor stage (first real test over a user VPN).

`audit_executor` runs in AWS and cannot reach a FortiGate that is only
reachable through a user VPN on the operator's workstation. This script runs
the same executor stage on that workstation instead: generation stays in AWS,
the generated script and its manifest are read from S3, and the read-only
audit is executed locally against the FortiGate.

It reuses the executor modules unchanged and keeps the gate order of
`handler_executor.lambda_handler`:

  1. read `artifacts/<run_id>/manifest.json` and the script from S3;
  2. integrity: SHA-256 of the script bytes against the manifest;
  3. independent re-validation with `script_validator.validate`;
  4. connectivity preflight: one GET through the client (`system_global`);
  5. `sandbox.execute` with the same toolkit and budget.

Differences with the Lambda, all deliberate:

  - The report is written ONLY to a local directory. Nothing is uploaded to
    S3 and nothing is published to SNS: `reports/<run_id>/report.json` in S3
    marks a run as done and would block running it again.
  - The FortiGate token comes from the `FORTIGATE_TOKEN` environment
    variable, never from a command-line argument or from Secrets Manager. It
    is never printed, logged or written to disk.
  - A failed preflight aborts with a non-zero exit code. Without it, an
    unreachable FortiGate yields a "completed" report full of `indeterminate`
    findings, because the client turns network errors into `None`.

Environment:
  S3_BUCKET                   reports bucket (or --bucket)
  FORTIGATE_HOST              host or host:port, no scheme
  FORTIGATE_TOKEN             REST API token (read-only profile)
  FORTIGATE_VERIFY_SSL        optional, default "true"
  SANDBOX_WALL_CLOCK_SECONDS  optional, same meaning as in the Lambda
  SANDBOX_MAX_FGT_CALLS       optional, same meaning as in the Lambda
  LOG_LEVEL                   optional, default INFO
  AWS credentials through the normal boto3 chain (AWS_PROFILE, AWS_REGION).

Usage (from audit-engine/):
  python scripts/run_executor_local.py <run_id>
  python scripts/run_executor_local.py <run_id> --output-dir C:/some/dir

Exit codes:
  0  audit completed, report written
  1  report written but the audit is not complete (integrity or validation
     rejection, execution error, sandbox budget exceeded)
  2  configuration or input error, nothing executed
  3  connectivity preflight failed, nothing executed

This file lives outside generator/, executor/, contracts/ and legacy/, which
are the only directories packaged into the Lambda zip: it is never deployed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ENGINE_DIR = SCRIPTS_DIR.parent
for _area in ("executor", "contracts"):
    if str(ENGINE_DIR / _area) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR / _area))

from botocore.exceptions import BotoCoreError, ClientError  # noqa: E402

import reporter  # noqa: E402
import s3_io  # noqa: E402
import sandbox  # noqa: E402
import script_validator  # noqa: E402
from fortigate_client import FortiGateClient  # noqa: E402

EXIT_OK = 0
EXIT_AUDIT_INCOMPLETE = 1
EXIT_CONFIG = 2
EXIT_PREFLIGHT = 3

DEFAULT_OUTPUT_DIR = ENGINE_DIR / "local-runs"
PREFLIGHT_ENDPOINT = "system_global"
REDACTED = "[REDACTED]"

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9]{1,64}")
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logger = logging.getLogger("run_executor_local")


class ConfigError(Exception):
    """Invalid configuration or input. The message is safe to print."""


class _RedactingFilter(logging.Filter):
    """Removes the token from every log record before a handler emits it.

    Defence in depth: this script never logs the token, but a dependency may
    embed it in an error text (http.client includes the header value in the
    error it raises for a malformed header, and the client logs that text).
    """

    def __init__(self, secret: str):
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if self._secret in message:
            record.msg = message.replace(self._secret, REDACTED)
            record.args = ()
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = formatted.replace(self._secret, REDACTED)
            record.exc_info = None
        elif record.exc_text and self._secret in record.exc_text:
            record.exc_text = record.exc_text.replace(self._secret, REDACTED)
        return True


def _redact(value, secret: str):
    """Returns `value` with every occurrence of `secret` replaced, recursively."""
    if isinstance(value, str):
        return value.replace(secret, REDACTED)
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(item, secret) for item in value]
    return value


def _run_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_executor_local.py",
        description=(
            "Run the executor stage locally against a FortiGate reachable from this "
            "machine. Read-only. The report is written to a local directory only."
        ),
        epilog="The FortiGate token is read from the FORTIGATE_TOKEN environment variable.",
        allow_abbrev=False,
    )
    parser.add_argument("run_id", help="run identifier (artifacts/<run_id>/ in the bucket)")
    parser.add_argument("--bucket", help="reports bucket; defaults to the S3_BUCKET variable")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"local directory for the report (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args(argv)


def _load_settings(args: argparse.Namespace) -> dict:
    """Reads and checks every input before any AWS or FortiGate call."""
    if not _RUN_ID_PATTERN.fullmatch(args.run_id or ""):
        raise ConfigError("Invalid run_id: expected 1 to 64 letters or digits.")

    bucket = args.bucket or os.environ.get("S3_BUCKET", "")
    host = os.environ.get("FORTIGATE_HOST", "").strip()
    token = os.environ.get("FORTIGATE_TOKEN", "").strip()

    missing = [
        name
        for name, value in (
            ("S3_BUCKET", bucket),
            ("FORTIGATE_HOST", host),
            ("FORTIGATE_TOKEN", token),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "Required environment variable(s) not set: "
            + ", ".join(missing)
            + ". See docs/context/local-executor-run.md."
        )
    if any(ch.isspace() or not ch.isprintable() for ch in token):
        raise ConfigError(
            "FORTIGATE_TOKEN contains whitespace or control characters. "
            "Set it again with the exact token value (it is not shown here)."
        )
    if "://" in host or "/" in host:
        raise ConfigError("FORTIGATE_HOST must be a host or host:port, without scheme or path.")

    try:
        budget = sandbox.SandboxBudget(
            max_wall_clock_s=float(
                os.environ.get(
                    "SANDBOX_WALL_CLOCK_SECONDS", sandbox.DEFAULT_BUDGET.max_wall_clock_s
                )
            ),
            max_fgt_calls=int(
                os.environ.get("SANDBOX_MAX_FGT_CALLS", sandbox.DEFAULT_BUDGET.max_fgt_calls)
            ),
        )
    except ValueError:
        raise ConfigError(
            "SANDBOX_WALL_CLOCK_SECONDS and SANDBOX_MAX_FGT_CALLS must be numbers."
        ) from None

    return {
        "run_id": args.run_id,
        "bucket": bucket,
        "host": host,
        "token": token,
        "verify_ssl": os.environ.get("FORTIGATE_VERIFY_SSL", "true").lower() == "true",
        "budget": budget,
        "output_dir": args.output_dir,
    }


def _read_artifacts(bucket: str, run_id: str) -> tuple[dict, str]:
    """Reads the manifest and the script it points to. Read-only S3 access."""
    manifest_key = f"artifacts/{run_id}/manifest.json"
    try:
        manifest = s3_io.get_manifest(bucket, manifest_key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "unknown")
        raise ConfigError(
            f"Could not read the manifest s3://{bucket}/{manifest_key} ({code}). "
            "Check the run_id, the bucket and the AWS profile and region."
        ) from None
    except BotoCoreError as e:
        raise ConfigError(
            f"Could not reach S3 to read the manifest ({type(e).__name__}). "
            "Check AWS_PROFILE and the region."
        ) from None
    except ValueError:
        raise ConfigError(f"The manifest s3://{bucket}/{manifest_key} is not valid JSON.") from None

    if not isinstance(manifest, dict) or manifest.get("run_id") != run_id:
        raise ConfigError("The manifest does not belong to this run_id.")
    script_key = manifest.get("script_key")
    if not isinstance(script_key, str) or not script_key.startswith(f"artifacts/{run_id}/"):
        raise ConfigError("The manifest has no script_key under this run's prefix.")

    try:
        script = s3_io.get_script(bucket, script_key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "unknown")
        raise ConfigError(
            f"Could not read the script s3://{bucket}/{script_key} ({code})."
        ) from None
    except (BotoCoreError, UnicodeDecodeError) as e:
        raise ConfigError(f"Could not read the script ({type(e).__name__}).") from None
    return manifest, script


def _preflight(client) -> bool:
    """One cheap GET through the existing client. `None` means it failed:
    the client logs the cause and swallows HTTP, TLS and network errors."""
    try:
        return client.get(PREFLIGHT_ENDPOINT) is not None
    except Exception as e:
        logger.error("Preflight raised %s", type(e).__name__)
        return False


def _preflight_failure_message(host: str, verify_ssl: bool) -> str:
    return "\n".join(
        [
            f"ERROR: preflight failed. The FortiGate at {host} did not answer a read-only "
            f"GET on '{PREFLIGHT_ENDPOINT}'. Nothing was executed and no report was written.",
            "The client log lines above show the HTTP status or the network error.",
            "Likely causes:",
            "  - The VPN (FortiClient) is not connected, or it does not route to that address.",
            "  - The trusted host of the REST API admin does not include the IP address",
            "    that the VPN assigned to this machine (HTTP 401 or 403, or a timeout).",
            "  - Wrong port: FORTIGATE_HOST accepts host:port when the admin HTTPS port",
            "    is not 443.",
            "  - Self-signed certificate: the log shows CERTIFICATE_VERIFY_FAILED. For a",
            f"    lab only, set FORTIGATE_VERIFY_SSL=false (current value: {verify_ssl}).",
            "  - Invalid or regenerated token, or a profile without read access (401/403).",
            "Check it by hand with the curl command in docs/context/local-executor-run.md.",
        ]
    )


def _write_report(
    settings: dict,
    manifest: dict,
    *,
    status: str,
    findings: list[dict],
    notes: list[dict],
    failure_reason: str | None,
    timestamp: str,
) -> Path:
    """Builds the report with the executor's own renderers and writes it locally."""
    token = settings["token"]
    run_id = settings["run_id"]
    policy_key = _redact(str(manifest.get("policy_key", "desconocida")), token)
    findings = _redact(findings, token)
    notes = _redact(notes, token)
    failure_reason = _redact(failure_reason, token)

    json_report = reporter.build_policy_report_json(
        findings, notes, status, run_id, policy_key, timestamp, failure_reason
    )
    # Additive key, present only in local reports: nothing consumes this file
    # from S3 because it is never uploaded.
    json_report["execution"] = {
        "mode": "local",
        "runner": "audit-engine/scripts/run_executor_local.py",
        "published": False,
    }
    markdown_report = reporter.build_policy_report_markdown(
        findings, notes, status, run_id, policy_key, timestamp, failure_reason
    )
    markdown_report += (
        "\n\n> **Ejecución local** (`audit-engine/scripts/run_executor_local.py`): "
        "este reporte no fue publicado en S3 ni notificado por SNS.\n"
    )

    target = Path(settings["output_dir"]) / run_id / _run_stamp()
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.json").write_text(
        json.dumps(json_report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (target / "report.md").write_text(markdown_report, encoding="utf-8")
    return target


def _print_summary(status: str, findings: list[dict], target: Path, failure_reason) -> None:
    counts: dict[str, int] = {}
    for finding in findings:
        key = str(finding.get("status", "indeterminate"))
        counts[key] = counts.get(key, 0) + 1
    by_status = ", ".join(f"{name}={count}" for name, count in sorted(counts.items())) or "none"
    print(f"Local run finished: status={status}")
    if failure_reason:
        print(f"Reason: {failure_reason}")
    print(f"Findings: {len(findings)} ({by_status})")
    print(f"Report (local only, not uploaded to S3, no SNS notification): {target}")


def _run(settings: dict) -> int:
    run_id = settings["run_id"]
    token = settings["token"]
    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    if not hasattr(signal, "setitimer"):
        _err(
            "WARNING: signal.setitimer is not available on this platform. The wall-clock "
            "backstop of the sandbox is OFF; only the per-call time and call-count limits "
            "apply. A generated script that never calls fgt/report is not interrupted."
        )

    manifest, script = _read_artifacts(settings["bucket"], run_id)

    def finish(status, findings, notes, failure_reason) -> int:
        target = _write_report(
            settings,
            manifest,
            status=status,
            findings=findings,
            notes=notes,
            failure_reason=failure_reason,
            timestamp=timestamp,
        )
        _print_summary(status, findings, target, _redact(failure_reason, token))
        return EXIT_OK if status == "completed" else EXIT_AUDIT_INCOMPLETE

    # 1. Integrity, before the AST is touched.
    actual_sha256 = hashlib.sha256(script.encode("utf-8")).hexdigest()
    if actual_sha256 != manifest.get("script_sha256"):
        _err(
            "ERROR: script integrity check failed (SHA-256 differs from the manifest). "
            "The script was NOT executed."
        )
        return finish("could_not_audit", [], [], "integrity_check_failed")

    # 2. Independent re-validation, from scratch.
    validation = script_validator.validate(script, manifest)
    if not validation.valid:
        failure_reason = f"revalidation_failed:{validation.errors[0].rule_id}"
        _err(f"ERROR: script re-validation failed ({failure_reason}). It was NOT executed.")
        return finish("could_not_audit", [], [], failure_reason)

    # 3. Connectivity preflight, before the sandbox.
    try:
        client = FortiGateClient(
            host=settings["host"], token=token, verify_ssl=settings["verify_ssl"]
        )
    except Exception as e:
        raise ConfigError(f"Could not build the FortiGate client ({type(e).__name__}).") from None
    if not _preflight(client):
        _err(_preflight_failure_message(settings["host"], settings["verify_ssl"]))
        return EXIT_PREFLIGHT
    print(f"Preflight OK: read-only GET on '{PREFLIGHT_ENDPOINT}' answered.")

    # 4. Execution under the sandbox, same toolkit and budget as the Lambda.
    try:
        result = sandbox.execute(script, manifest, client, budget=settings["budget"])
    except sandbox.SandboxBudgetExceeded as e:
        notes = [
            *e.notes,
            {"check_id": "_sandbox", "message": f"execution terminated early: {e.reason} — {e}"},
        ]
        return finish("truncated", e.findings, notes, e.reason)
    except Exception as e:
        _err(f"ERROR: the script failed while running ({type(e).__name__}).")
        return finish("could_not_audit", [], [], f"execution_error:{type(e).__name__}:{e}")

    return finish("completed", result.findings, result.notes, None)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        settings = _load_settings(args)
    except ConfigError as e:
        _err(f"ERROR: {e}")
        return EXIT_CONFIG

    root = logging.getLogger()
    previous_level = root.level
    redacting_filter = _RedactingFilter(settings["token"])
    own_handler = logging.StreamHandler(sys.stderr)
    own_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    filtered_handlers = [*root.handlers, own_handler]
    for handler in filtered_handlers:
        handler.addFilter(redacting_filter)
    root.addHandler(own_handler)
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    if previous_level == logging.NOTSET or previous_level > level:
        root.setLevel(level)

    try:
        return _run(settings)
    except ConfigError as e:
        _err(f"ERROR: {e}")
        return EXIT_CONFIG
    finally:
        root.removeHandler(own_handler)
        for handler in filtered_handlers:
            handler.removeFilter(redacting_filter)
        root.setLevel(previous_level)


if __name__ == "__main__":
    sys.exit(main())
