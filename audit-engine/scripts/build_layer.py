#!/usr/bin/env python3
"""
Construye el Lambda Layer `pps-doc-parsers` (equivalente multiplataforma de
`build_layer.sh`, solo stdlib).

Empaqueta pypdf + python-docx (+ lxml) para el parsing de políticas
PDF/DOCX que hace `policy_generator` (ver `terraform/lambda.tf`,
`aws_lambda_layer_version.doc_parsers`). Funciona igual en Windows, macOS y
Linux porque le pide a pip wheels precompiladas para el runtime real de
Lambda (`manylinux2014_x86_64`, CPython 3.12) en vez de compilar nada contra
el sistema local:

    pip install --platform manylinux2014_x86_64 --only-binary=:all:
                --python-version 3.12 --implementation cp
                --target <tmp>/python -r scripts/layer-requirements.txt

El intérprete que corre este script no necesita ser 3.12 (cualquier 3.9+
con pip sirve): `--python-version` le indica a pip para qué versión
resolver, independientemente de con cuál se ejecuta.

Layout del zip (requisito de Lambda Layers): todo bajo un directorio
top-level `python/`, que Lambda agrega al PYTHONPATH de la función.

IMPORTANTE: boto3/botocore NO entran en el layer. El runtime python3.12 de
Lambda ya los trae preinstalados y `layer-requirements.txt` no los lista,
así que pip tampoco los arrastra como dependencia transitiva (pypdf,
python-docx y lxml no dependen de boto3). Este script lo verifica al final
y falla si aparecieran.

Uso:
    python scripts/build_layer.py
    python scripts/build_layer.py --python C:/ruta/a/python.exe
    python scripts/build_layer.py --output layers/pps-doc-parsers.zip

Imprime la ruta absoluta del zip y su tamaño. Código de salida 0 si todo
salió bien, distinto de 0 ante cualquier fallo de pip o de verificación.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PYTHON_VERSION = "3.12"
PLATFORM = "manylinux2014_x86_64"
IMPLEMENTATION = "cp"

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_REQUIREMENTS = SCRIPT_DIR / "layer-requirements.txt"
DEFAULT_OUTPUT = REPO_ROOT / "layers" / "pps-doc-parsers.zip"

# Paquetes que jamás deben viajar en el layer: el runtime de Lambda ya los
# provee y duplicarlos solo agrega tamaño y riesgo de conflicto de versión.
FORBIDDEN_TOP_LEVEL = ("boto3", "botocore", "s3transfer")

# Marcadores que confirman que el contenido esperado quedó en el layout
# correcto (`python/<paquete>/__init__.py`).
EXPECTED_MARKERS = (
    "python/pypdf/__init__.py",
    "python/docx/__init__.py",
    "python/lxml/__init__.py",
)


def _run_pip(python_bin: str, target_dir: Path, requirements: Path) -> None:
    cmd = [
        python_bin,
        "-m",
        "pip",
        "install",
        "--platform",
        PLATFORM,
        "--python-version",
        PYTHON_VERSION,
        "--implementation",
        IMPLEMENTATION,
        "--only-binary=:all:",
        "--target",
        str(target_dir),
        "--requirement",
        str(requirements),
        "--disable-pip-version-check",
    ]
    print("==> pip:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def _prune(target_dir: Path) -> None:
    """Elimina artefactos que no aportan en runtime (bytecode, dist-info de
    pip, binarios de consola) para reducir el tamaño del layer."""
    for path in target_dir.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
    bin_dir = target_dir / "bin"
    if bin_dir.is_dir():
        shutil.rmtree(bin_dir, ignore_errors=True)


def _write_zip(build_dir: Path, output_zip: Path) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(build_dir):
            for name in sorted(files):
                full_path = Path(root) / name
                # arcname SIEMPRE con '/' (zip spec), aunque se construya en Windows.
                arcname = full_path.relative_to(build_dir).as_posix()
                zf.write(full_path, arcname)


def _verify(output_zip: Path) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(output_zip) as zf:
        names = set(zf.namelist())
    for marker in EXPECTED_MARKERS:
        if marker not in names:
            problems.append(f"falta {marker} en el zip (layout python/<paquete>/ incorrecto)")
    for forbidden in FORBIDDEN_TOP_LEVEL:
        if any(n.startswith(f"python/{forbidden}/") for n in names):
            problems.append(f"{forbidden} no debe incluirse en el layer (lo provee el runtime)")
    return problems


def build(python_bin: str, requirements: Path, output_zip: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="pps-layer-") as tmp:
        build_dir = Path(tmp)
        package_dir = build_dir / "python"
        package_dir.mkdir(parents=True)
        _run_pip(python_bin, package_dir, requirements)
        _prune(package_dir)
        _write_zip(build_dir, output_zip)

    problems = _verify(output_zip)
    if problems:
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        raise SystemExit(2)
    return output_zip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construye layers/pps-doc-parsers.zip")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Intérprete con pip para resolver/bajar las wheels (default: el actual)",
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    output = build(args.python, args.requirements.resolve(), args.output.resolve())
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"==> Layer listo: {output} ({size_mb:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
