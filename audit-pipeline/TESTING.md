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
pip install -r lambda/requirements.txt
```

`lambda/requirements.txt` trae `pypdf`/`python-docx`/`lxml` — dependencias de
runtime de `extractor.py` (policy_generator), pineadas a la misma versión
que el Lambda Layer `pps-doc-parsers` (ver `scripts/layer-requirements.txt`).
Sin este segundo `pip install`, los tests de `test_extractor.py` fallan por
`ModuleNotFoundError`.

## 2. Correr los tests (pytest)

```bash
pytest
```

Corre toda la suite en `lambda/tests/` — **164 tests passed, 1 skipped**
(skip documentado: `signal.setitimer`/`SIGALRM` no existe en Windows, ver
`test_sandbox.py::TestWallClockBudgetViaSignalBackstop`). Todos mockean AWS
(S3/Secrets Manager/SNS/`lambda:InvokeFunction`)/FortiGate/Claude — nunca se
hace red real, se puede correr sin credenciales ni conectividad.

### Archivos de test — flujo legacy NIST CSF 2.0 (`enable_legacy_nist_schedule=true`, default)

| Archivo | Qué cubre |
|---|---|
| `test_fortigate_client.py` | Cliente REST FortiGate — `collect_all()` legacy + `get(endpoint_key)` público memoizado (task 6.3) |
| `test_analyzer.py` | Prompt building + llamada a Claude del análisis NIST CSF 2.0 hardcodeado |
| `test_handler.py` | Orquestación del Lambda `assessor` legacy + contrato de env vars con `terraform/lambda.tf` |
| `test_reporter.py` | Reporte Markdown/JSON/SNS del análisis NIST (funciones legacy, sin cambios) + capa policy-agnostic (ver abajo) |

### Archivos de test — flujo policy-driven audit script generation (Fases 3-8)

| Archivo | Qué cubre |
|---|---|
| `test_extractor.py` | Extracción de texto PDF/DOCX; falla explícita ante corrupción/encriptación/sin capa de texto |
| `test_chunker.py` | Chunking preservando límites de cláusula/sección + retrieval TF-IDF |
| `test_script_validator.py` | Allowlist AST (happy-path + corpus adversarial RED completo: reflexión, imports, builtins denegados, caps estáticas) |
| `test_toolkit.py` | Capabilities `fgt`/`report` inyectadas en el sandbox — memoización, resolución server-side de `clause_ref` |
| `test_sandbox.py` | Namespace restringido + presupuestos duros (wall-clock, call-count, findings) — `SandboxBudgetExceeded` |
| `test_llm_client.py` | Fase map (chunk group → `PolicyCheck[]`) + fase reduce con reintento acotado (`MAX_GENERATION_ATTEMPTS`) |
| `test_s3_io.py` | Get/put de policy/script/manifest/report; integridad `script_sha256` end-to-end |
| `test_reporter.py` (clases `TestBuildPolicyReport*`, `TestDeliverPolicyReport`) | Reporte policy-agnostic keyed en `Finding`/`RunManifest`; distingue tres status: `completed` (auditoría íntegra), `truncated` (corte de presupuesto de sandbox, hallazgos parciales SÍ se muestran en tabla, header de advertencia visualmente equivalente a `could_not_audit`) y `could_not_audit` (nada auditable, sin tabla de hallazgos) — JSON incluye flag booleano de primer nivel `truncated` |
| `test_handler_generator.py` | Entrypoint S3-triggered `policy_generator` — flujo feliz completo, camino de reintentos agotados (`generation_failed`, no invoca executor), camino sin controles verificables (`no_verifiable_controls`, no invoca executor), fallo de extracción |
| `test_handler_executor.py` | Entrypoint async `audit_executor` — re-validación independiente exitosa ejecuta y reporta; re-validación fallida NO ejecuta; chequeo de integridad `script_sha256` rechaza ANTES de tocar el AST; tolerancia a fallo parcial de un endpoint FortiGate; presupuesto de sandbox agotado reporta `status="truncated"` (nunca `"completed"`) preservando los hallazgos parciales recolectados antes del corte |
| `test_integration_generator_executor.py` | Contrato generator→executor de punta a punta con S3 real (`moto`): el manifest+script que escribe el generador llegan sin cambios al executor; un script alterado en S3 entre ambos handlers se rechaza por integridad |

Útil:

```bash
pytest -v                    # verbose, un test por línea
pytest lambda/tests/test_handler.py   # un solo módulo
pytest -k "truncat"          # filtrar por nombre
pytest lambda/tests/test_handler_generator.py lambda/tests/test_handler_executor.py lambda/tests/test_integration_generator_executor.py -v  # solo Fase 8
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

## 5. `terraform validate` / `plan` — OJO con Google Drive

Igual que con checkov, Google Drive Desktop interfiere acá, pero de forma
más grave: `terraform init` descarga los binarios de los providers
(`terraform-provider-aws.exe`, etc.) dentro de `.terraform/providers/`, y
Drive los toca al sincronizarlos — el resultado es que el hash del binario
en disco no coincide con el que quedó grabado en `.terraform.lock.hcl`, y
`terraform validate`/`plan` fallan con:

```
Error: missing or corrupted provider plugins:
  - registry.terraform.io/hashicorp/aws: the cached package ... does not
    match any of the checksums recorded in the dependency lock file
```

Reinicializar (`rm -rf .terraform .terraform.lock.hcl && terraform init`)
**no alcanza** — Drive vuelve a corromper el binario. La solución real es
sacar el directorio de trabajo de Terraform (`.terraform/`) de la carpeta
sincronizada, apuntando `TF_DATA_DIR` a un path local fuera de Google Drive:

```bash
export TF_DATA_DIR="C:/Users/santi/.terraform-data/pps-audit-pipeline"
mkdir -p "$TF_DATA_DIR"
terraform init -backend=false -input=false
terraform validate
```

Los archivos `.tf` (código fuente) se quedan en Drive sin problema — el
único directorio que hay que sacar de ahí es `.terraform/` (los binarios
descargados), que ya está en `.gitignore` de todas formas. Conviene exportar
esa variable en tu perfil de shell si vas a correr Terraform seguido en este
proyecto.

## 6. tflint (pendiente — instalación manual opcional)

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
