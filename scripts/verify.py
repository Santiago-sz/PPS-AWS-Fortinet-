"""Verificacion local/CI sin despliegues. Ejecutar con el Python del entorno dev."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
IAC_ROOTS = ("terraform", "audit-pipeline/terraform", "fortigate-sandbox-2026-06-07")


@dataclass(frozen=True)
class Step:
    name: str
    cwd: str
    command: tuple[str, ...]


def python_step(name: str, cwd: str, *args: str) -> Step:
    return Step(name, cwd, (sys.executable, *args))


def profiles() -> dict[str, list[Step]]:
    return {
        "harness": [
            python_step(
                "harness-tests",
                ".",
                "-m",
                "unittest",
                "discover",
                "-s",
                "scripts/tests",
                "-v",
            ),
            python_step(
                "harness-lint",
                ".",
                "-m",
                "ruff",
                "check",
                "--config",
                "desktop/pyproject.toml",
                "scripts",
            ),
        ],
        "pipeline": [
            python_step(
                "pipeline-tests",
                "audit-pipeline",
                "-m",
                "pytest",
                "-q",
                "-c",
                "pyproject.toml",
                "lambda/tests",
            ),
            python_step(
                "pipeline-lint", "audit-pipeline", "-m", "ruff", "check", "lambda"
            ),
        ],
        "api": [
            python_step(
                "api-tests",
                "audit-pipeline/api",
                "-m",
                "pytest",
                "-q",
                "-c",
                "pyproject.toml",
                "tests",
            ),
            python_step(
                "api-lint",
                ".",
                "-m",
                "ruff",
                "check",
                "--config",
                "desktop/pyproject.toml",
                "audit-pipeline/api",
            ),
        ],
        "desktop": [
            python_step(
                "desktop-tests",
                "desktop",
                "-m",
                "pytest",
                "-q",
                "-c",
                "pyproject.toml",
                "tests",
            ),
            python_step("desktop-lint", "desktop", "-m", "ruff", "check", "."),
        ],
        "iac": [
            python_step("iac-parse", ".", "scripts/check_iac.py"),
            *(
                Step(
                    f"iac-fmt-{i}",
                    directory,
                    ("terraform", "fmt", "-check", "."),
                )
                for i, directory in enumerate(IAC_ROOTS, 1)
            ),
        ],
    }


def verification_env() -> dict[str, str]:
    # Evitar que boto3 use perfiles o credenciales reales del desarrollador.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("AWS_")}
    for key in ("PYTHONPATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        env.pop(key, None)
    env.update(
        {
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "BOTO_CONFIG": os.devnull,
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def run_step(step: Step, report_dir: Path, timeout: float) -> dict:
    started = time.monotonic()
    log = report_dir / f"{step.name}.log"
    print(f"\n[{step.name}] ({step.cwd}) {' '.join(step.command)}", flush=True)
    status, code = "failed", None
    with log.open("w", encoding="utf-8") as output:
        try:
            result = subprocess.run(
                step.command,
                cwd=ROOT / step.cwd,
                env=verification_env(),
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            code = result.returncode
            status = "passed" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "timeout"
            output.write(f"\nTiempo limite agotado: {timeout}s\n")
        except OSError as error:
            status = "unavailable"
            output.write(f"No se pudo ejecutar el control: {error}\n")
    # El log completo queda como artefacto; la consola conserva el resumen.
    print(
        "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
    )
    print(f"[{step.name}] {status}", flush=True)
    return {
        "name": step.name,
        "cwd": step.cwd,
        "command": list(step.command),
        "status": status,
        "returncode": code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "log": str(log),
    }


def main(argv: list[str] | None = None) -> int:
    available = profiles()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profiles", nargs="*", help="harness pipeline api desktop iac; default: todos"
    )
    parser.add_argument(
        "--list", action="store_true", help="Mostrar controles sin ejecutarlos"
    )
    parser.add_argument("--report-dir", type=Path, default=ROOT / ".harness/reports")
    parser.add_argument(
        "--timeout", type=float, default=180, help="Segundos maximos por control"
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout debe ser mayor que cero")
    selected = list(dict.fromkeys(args.profiles or available))
    if unknown := set(selected) - available.keys():
        parser.error(f"Perfiles desconocidos: {', '.join(sorted(unknown))}")
    steps = [step for name in selected for step in available[name]]
    if args.list:
        for step in steps:
            print(f"{step.name}: [{step.cwd}] {' '.join(step.command)}")
        return 0
    args.report_dir.mkdir(parents=True, exist_ok=True)
    results = [run_step(step, args.report_dir, args.timeout) for step in steps]
    passed = all(result["status"] == "passed" for result in results)
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "profiles": selected,
        "status": "passed" if passed else "failed",
        "steps": results,
    }
    target = args.report_dir / "verification.json"
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nResultado: {report['status']}. Reporte: {target}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
