#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# BUILD_LAYER.SH — Construye el Lambda Layer pps-doc-parsers
# =============================================================================
# Empaqueta pypdf + python-docx (+ lxml) para el parsing de políticas
# PDF/DOCX que hace policy_generator (ver terraform/lambda.tf,
# aws_lambda_layer_version.doc_parsers, y design.md decisión #8).
#
# Usa `pip install --platform manylinux2014_x86_64 --python-version 3.12
# --only-binary=:all:` para bajar wheels precompiladas del runtime real de
# Lambda (Amazon Linux x86_64), sin importar en qué SO corra este script
# (Windows/macOS/Linux) ni qué build de Python tenga instalada la máquina
# de desarrollo. --only-binary=:all: es lo que evita que pip intente
# compilar lxml desde source contra las librerías del SO local.
#
# AWS Lambda Layers requieren que las dependencias vivan bajo un directorio
# top-level llamado `python/` dentro del zip — Lambda lo agrega
# automáticamente al PYTHONPATH de la función al momento de ejecutar.
#
# PREREQUISITO de terraform init/plan/apply: aws_lambda_layer_version.doc_parsers
# en terraform/lambda.tf referencia el zip que este script genera vía
# `filename` + `filebase64sha256(...)`. Correr este script ANTES de
# cualquier comando de Terraform que toque ese recurso — si el zip no
# existe, filebase64sha256() falla con "no file exists".
#
# Uso:
#   ./scripts/build_layer.sh
#   PYTHON_BIN=/ruta/a/python ./scripts/build_layer.sh   (para forzar un intérprete puntual)
# =============================================================================

PYTHON_VERSION="3.12"
PLATFORM="manylinux2014_x86_64"
IMPLEMENTATION="cp"

# -----------------------------------------------------------------------------
# Resolución del intérprete Python usado para correr pip.
# No necesita ser Python 3.12 — --python-version le dice a pip para QUÉ
# versión de Python resolver/bajar wheels, independientemente de con qué
# intérprete se ejecuta pip mismo. Alcanza con cualquier Python 3.9+.
# -----------------------------------------------------------------------------

if [ -n "${PYTHON_BIN:-}" ]; then
  : # respetar override explícito del caller
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "ERROR: no se encontró python3 ni python en PATH." >&2
  echo "       Activá el venv del proyecto o exportá PYTHON_BIN=/ruta/a/python.exe" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${REPO_ROOT}/layers/build"
PACKAGE_DIR="${BUILD_DIR}/python"
OUTPUT_ZIP="${REPO_ROOT}/layers/pps-doc-parsers.zip"
REQUIREMENTS_FILE="${SCRIPT_DIR}/layer-requirements.txt"

echo "==> Usando intérprete: ${PYTHON_BIN} ($("${PYTHON_BIN}" --version 2>&1))"

echo "==> Limpiando build anterior (${BUILD_DIR})"
rm -rf "${BUILD_DIR}"
mkdir -p "${PACKAGE_DIR}"

echo "==> Instalando dependencias (${PLATFORM}, Python ${PYTHON_VERSION}, solo wheels binarias)"
"${PYTHON_BIN}" -m pip install \
  --platform "${PLATFORM}" \
  --python-version "${PYTHON_VERSION}" \
  --implementation "${IMPLEMENTATION}" \
  --only-binary=:all: \
  --target "${PACKAGE_DIR}" \
  --requirement "${REQUIREMENTS_FILE}"

echo "==> Empaquetando ${OUTPUT_ZIP}"
mkdir -p "${REPO_ROOT}/layers"
rm -f "${OUTPUT_ZIP}"

# Se arma el zip con el módulo estdlib zipfile (en vez de invocar un
# binario `zip` externo) porque no está garantizado que exista en PATH en
# todas las plataformas de desarrollo (ej. Git Bash en Windows sin
# herramientas GNU adicionales instaladas) — python sí, siempre.
"${PYTHON_BIN}" - "${BUILD_DIR}" "${OUTPUT_ZIP}" <<'PYEOF'
import os
import sys
import zipfile

build_dir, output_zip = sys.argv[1], sys.argv[2]

with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, _dirs, files in os.walk(build_dir):
        for name in files:
            full_path = os.path.join(root, name)
            arcname = os.path.relpath(full_path, build_dir)
            zf.write(full_path, arcname)

print(f"Wrote {output_zip}")
PYEOF

SIZE="$(du -h "${OUTPUT_ZIP}" | cut -f1)"
echo "==> Listo: ${OUTPUT_ZIP} (${SIZE})"
echo "    Ahora podés correr terraform init/plan/apply en terraform/."
