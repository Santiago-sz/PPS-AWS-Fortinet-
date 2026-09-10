# Testing y calidad de código

Guía rápida para correr tests, linter y análisis estático de IaC en este
proyecto (Lambda Python + Terraform).

## 1. Activar el entorno virtual

El venv ya está creado en `.venv/` (Python 3.12) con todas las dependencias
de desarrollo instaladas (`requirements-dev.txt`).

En Git Bash / WSL:

```bash
source .venv/Scripts/activate
```

En PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Si el venv no existe todavía (clon nuevo del repo), recrearlo con:

```bash
"/c/Users/santi/AppData/Local/Programs/Python/Python312/python.exe" -m venv .venv
source .venv/Scripts/activate
pip install -r requirements-dev.txt
```

## 2. Correr los tests (pytest)

```bash
pytest
```

Corre toda la suite en `lambda/tests/` (35 tests: `fortigate_client.py`,
`analyzer.py`, `reporter.py`, `handler.py`). Todos mockean AWS/FortiGate/
Claude — no hacen llamadas de red reales, se pueden correr sin credenciales
ni conectividad.

Útil:

```bash
pytest -v                    # verbose, un test por línea
pytest lambda/tests/test_handler.py   # un solo módulo
pytest -k "truncat"          # filtrar por nombre
```

La configuración de pytest vive en `pyproject.toml` (`[tool.pytest.ini_options]`):
agrega `lambda/` al `pythonpath` para que los tests puedan hacer
`from handler import lambda_handler` igual que en el runtime real de Lambda
(que deposita todos los `.py` sueltos en la raíz del paquete de despliegue).

## 3. Correr el linter (ruff)

```bash
ruff check lambda/          # lint (pyflakes + pycodestyle + isort + pyupgrade + bugbear)
ruff format --check lambda/ # verifica formato sin modificar
ruff format lambda/         # aplica el formato
```

Configuración en `pyproject.toml` (`[tool.ruff]` / `[tool.ruff.lint]`).

## 4. Correr checkov sobre Terraform

Hay dos directorios Terraform **independientes** — correr checkov por
separado en cada uno:

```bash
PYTHONUTF8=1 python -m checkov.main -d terraform
PYTHONUTF8=1 python -m checkov.main -d P-Terraform-Forti-AWS
```

`PYTHONUTF8=1` es necesario en Windows: sin eso, Python usa cp1252 por
defecto para leer archivos y checkov revienta con `UnicodeDecodeError` al
toparse con los comentarios en español (tildes, guiones largos) de los
`.tf`.

Es un análisis de solo lectura — checkov nunca corre `terraform plan` ni
`apply`, solo parsea el HCL estáticamente. El resultado consolidado de la
última corrida está en `checkov-report.md`.

### Nota: proyecto sincronizado con Google Drive

Este proyecto vive dentro de una carpeta de Google Drive Desktop
(`G:\Mi unidad\...`). Google Drive inyecta un archivo `desktop.ini` en cada
carpeta del árbol — incluyendo dentro de `.venv/Lib/site-packages/`. Una de
las dependencias de checkov (`jsonschema_specifications`) recorre
recursivamente su carpeta de esquemas y intenta parsear **todo** archivo
como JSON, así que un `desktop.ini` ahí adentro rompe la corrida con
`JSONDecodeError`. Si eso pasa, limpiar los `desktop.ini` del venv antes de
correr checkov:

```bash
find .venv -iname "desktop.ini" -delete
```

(Van a reaparecer con el tiempo porque Google Drive los recrea — no es
necesario evitarlo permanentemente, solo limpiarlos antes de correr
checkov si falla con ese error puntual.)

## 5. tflint (pendiente — instalación manual opcional)

`tflint` no está instalado en este entorno: requiere descargar un binario y
agregarlo al PATH, y no había gestor de paquetes (`choco`/`scoop`/`winget`)
disponible en la shell usada para automatizar la instalación.

Para instalarlo manualmente en Windows, ver la guía oficial:
https://github.com/terraform-linters/tflint/blob/master/docs/user-guide/install.md

(en Windows sin choco/scoop, la opción más simple es descargar el `.zip` de
la release desde https://github.com/terraform-linters/tflint/releases y
agregar el binario al PATH del usuario).

Una vez instalado, correr desde cada directorio Terraform:

```bash
cd terraform && tflint --init && tflint
cd P-Terraform-Forti-AWS && tflint --init && tflint
```
