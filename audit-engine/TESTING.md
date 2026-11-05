# Testing y calidad de código

Guía rápida para correr tests, linter y análisis estático de IaC en este
proyecto (Lambda Python + Terraform).

## 1. Entorno virtual

El venv vive en la **raíz del repositorio** (`../.venv` visto desde
`audit-engine/`), Python 3.12, con las dependencias de desarrollo
(`requirements-dev.txt`) y de runtime (`requirements.txt`) instaladas.
Está ignorado por Git (`.venv/` en el `.gitignore` raíz).

Si el venv no existe todavía (clon nuevo del repo), recrearlo desde la raíz:

```bash
python -m venv .venv
cd audit-engine
../.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
../.venv/Scripts/python.exe -m pip install -r requirements.txt
```

`requirements.txt` trae `pypdf`/`python-docx`/`lxml` — dependencias de
runtime de `extractor.py` (policy_generator), pineadas a la misma versión
que el Lambda Layer `pps-doc-parsers` (ver `scripts/layer-requirements.txt`).
Sin este segundo `pip install`, los tests de `test_extractor.py` fallan por
`ModuleNotFoundError`.

Todos los comandos de abajo se corren desde `audit-engine/` invocando el
intérprete del venv directamente (no hace falta activarlo):

```bash
cd audit-engine
../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

## 2. Correr los tests (pytest)

```bash
../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Corre toda la suite en `tests/` — **275 tests passed, 1 skipped**
(skip documentado: `signal.setitimer`/`SIGALRM` no existe en Windows, ver
`test_sandbox.py::TestWallClockBudgetViaSignalBackstop`; en Linux/CI ese
test corre de verdad y la suite reporta 276 passed, 0 skipped). Todos mockean AWS
(S3/Secrets Manager/SNS/`lambda:InvokeFunction`/Bedrock)/FortiGate — nunca se
hace red real, se puede correr sin credenciales ni conectividad.

Nota: el `botocore` del venv (1.35.x) es anterior al bloque `cachePoint` de
la API Converse de Bedrock, así que no sirve para validar localmente la
request real contra el modelo; los tests reemplazan el cliente
`bedrock-runtime` por un mock y verifican la forma del payload a mano. El
runtime de Lambda trae un boto3 más nuevo.

### Archivos de test — infraestructura compartida

| Archivo | Qué cubre |
|---|---|
| `test_bedrock_client.py` | Transporte Converse sobre Bedrock: forma exacta de la request (`modelId`, `cachePoint`, `maxTokens` explícito), parseo de usage/latencia, mapeo de errores a `BedrockCallError`, cliente cacheado, evento `llm_call` + métricas EMF |
| `test_observability.py` | `log_event` (una línea JSON), `emit_metric` (estructura EMF `_aws`), `timer` |

### Archivos de test — flujo legacy NIST CSF 2.0 (`enable_legacy_nist_schedule=false` por defecto; la Lambda assessor sigue desplegada)

| Archivo | Qué cubre |
|---|---|
| `test_fortigate_client.py` | Cliente REST FortiGate — `collect_all()` legacy + `get(endpoint_key)` público memoizado (task 6.3) |
| `test_analyzer.py` | Prompt building + llamada al modelo vía Bedrock del análisis NIST CSF 2.0 hardcodeado (`{"error": "bedrock_error"}` ante fallos, nunca levanta) |
| `test_handler.py` | Orquestación del Lambda `assessor` legacy + contrato de env vars con `../infrastructure/pipeline/lambda.tf` (incluye que `CLAUDE_SECRET_ARN` ya no se inyecta y `BEDROCK_MODEL_ID` sí) |
| `test_reporter.py` | Reporte Markdown/JSON/SNS del análisis NIST (funciones legacy, sin cambios) + capa policy-agnostic (ver abajo) |

### Archivos de test — flujo policy-driven audit script generation (Fases 3-8)

| Archivo | Qué cubre |
|---|---|
| `test_extractor.py` | Extracción de texto PDF/DOCX; falla explícita ante corrupción/encriptación/sin capa de texto |
| `test_chunker.py` | Chunking preservando límites de cláusula/sección + retrieval TF-IDF |
| `test_script_validator.py` | Allowlist AST (happy-path + corpus adversarial RED completo: reflexión, imports, builtins denegados, caps estáticas) |
| `test_toolkit.py` | Capabilities `fgt`/`report` inyectadas en el sandbox — memoización, resolución server-side de `clause_ref` y de la `remediation` propuesta |
| `test_sandbox.py` | Namespace restringido + presupuestos duros (wall-clock, call-count, findings) — `SandboxBudgetExceeded` |
| `test_llm_client.py` | Fase map (chunk group → `PolicyCheck[]`, normalización de `remediation`) + fase reduce con reintento acotado (`MAX_GENERATION_ATTEMPTS`); eventos `llm_call`/`generation_result` |
| `test_s3_io.py` | Get/put de policy/script/manifest/report; integridad `script_sha256` end-to-end |
| `test_reporter.py` (clases `TestBuildPolicyReport*`, `TestRemediation*`, `TestDeliverPolicyReport`) | Reporte policy-agnostic keyed en `Finding`/`RunManifest`; distingue tres status: `completed`, `truncated` (hallazgos parciales SÍ se muestran) y `could_not_audit`; sección `## Remediaciones propuestas` (solo propuestas, nunca aplicadas); JSON con `remediation` por hallazgo y `remediation_count`; escritura en `reports/{run_id}/report.{md,json}` |
| `test_handler_generator.py` | Entrypoint S3-triggered `policy_generator` — flujo feliz, compuerta `AUTO_EXECUTE` (`awaiting_approval` sin invocar executor), reintentos agotados, sin controles verificables, fallo del modelo, fallo de extracción; evento `generator_result` |
| `test_handler_executor.py` | Entrypoint async `audit_executor` — re-validación independiente; integridad `script_sha256` ANTES del AST; tolerancia a fallo parcial de endpoint; presupuesto agotado reporta `status="truncated"` |
| `test_integration_generator_executor.py` | Contrato generator→executor de punta a punta con S3 real (`moto`): manifest+script llegan sin cambios; script alterado se rechaza; `report.json`/`report.md` quedan donde el bridge local los busca; `AUTO_EXECUTE=false` deja artifacts firmados sin invocar |
| `test_evals_offline.py` | Smoke test del harness de evals (`evals/run_evals.py --mode offline`) en el mismo proceso: exit 0, archivo de resultados, métricas presentes, el ciclo de reintento ejercitado por una fixture, `bedrock_client.converse` restaurado |

Útil:

```bash
../.venv/Scripts/python.exe -m pytest -v                    # verbose, un test por línea
../.venv/Scripts/python.exe -m pytest tests/test_handler.py   # un solo módulo
../.venv/Scripts/python.exe -m pytest -k "truncat"          # filtrar por nombre
../.venv/Scripts/python.exe -m pytest tests/test_handler_generator.py tests/test_handler_executor.py tests/test_integration_generator_executor.py -v  # solo Fase 8
```

La configuración de pytest vive en `pyproject.toml` (`[tool.pytest.ini_options]`):
agrega las áreas del motor al `pythonpath` para que los tests puedan hacer
`from handler import lambda_handler` igual que en el runtime real de Lambda
(que deposita todos los `.py` sueltos en la raíz del paquete de despliegue).

## 3. Correr el linter (ruff)

```bash
../.venv/Scripts/python.exe -m ruff check generator/ executor/ contracts/ legacy/ tests/          # lint (pyflakes + pycodestyle + isort + pyupgrade + bugbear)
../.venv/Scripts/python.exe -m ruff format --check generator/ executor/ contracts/ legacy/ tests/ # verifica formato sin modificar
../.venv/Scripts/python.exe -m ruff format generator/ executor/ contracts/ legacy/ tests/         # aplica el formato
```

Configuración en `pyproject.toml` (`[tool.ruff]` / `[tool.ruff.lint]`).

## 4. Correr checkov sobre Terraform

```bash
PYTHONUTF8=1 ../.venv/Scripts/python.exe -m checkov.main -d ../infrastructure/pipeline
```

`PYTHONUTF8=1` es necesario en Windows: sin eso, Python usa cp1252 por
defecto para leer archivos y checkov revienta con `UnicodeDecodeError` al
toparse con los comentarios en español (tildes, guiones largos) de los
`.tf`.

Es un análisis de solo lectura — checkov nunca corre `terraform plan` ni
`apply`, solo parsea el HCL estáticamente. El resultado consolidado de la
última corrida está en `checkov-report.md`.

## 5. `terraform validate` / `plan`

Conviene mantener el directorio de trabajo de Terraform (`.terraform/`, con
los binarios de los providers) fuera del árbol del repositorio apuntando
`TF_DATA_DIR` a un path local. Evita que herramientas de sincronización o
antivirus toquen los binarios descargados y rompan el checksum registrado en
`.terraform.lock.hcl` (`Error: missing or corrupted provider plugins`):

```bash
export TF_DATA_DIR="C:/Users/<usuario>/.terraform-data/pps-audit-pipeline"
mkdir -p "$TF_DATA_DIR"
cd ../infrastructure/pipeline
terraform init -backend=false -input=false
terraform validate
```

Los archivos `.tf` (código fuente) se quedan en el repo; el único directorio
que se saca es `.terraform/`, que ya está en `.gitignore` de todas formas.
Conviene exportar esa variable en el perfil de shell si se va a correr
Terraform seguido en este proyecto.

Prerrequisito: `layers/pps-doc-parsers.zip` tiene que existir antes de
`validate`/`plan`/`apply` (ver sección "Layer"), porque
`aws_lambda_layer_version.doc_parsers` calcula `filebase64sha256()` sobre
él. También `terraform fmt -check -recursive` debe pasar (CI lo exige).

## 6. tflint (pendiente — instalación manual opcional)

`tflint` no está instalado en este entorno: requiere descargar un binario y
agregarlo al PATH.

Para instalarlo manualmente en Windows, ver la guía oficial:
https://github.com/terraform-linters/tflint/blob/master/docs/user-guide/install.md

(en Windows sin choco/scoop, la opción más simple es descargar el `.zip` de
la release desde https://github.com/terraform-linters/tflint/releases y
agregar el binario al PATH del usuario).

Una vez instalado, correr desde el directorio Terraform:

```bash
cd ../infrastructure/pipeline && tflint --init && tflint
```

## 7. Layer (`layers/pps-doc-parsers.zip`)

El Lambda Layer con `pypdf` + `python-docx` + `lxml` (solo lo monta
`policy_generator`) se construye con cualquiera de los dos scripts
equivalentes; el `.py` es el recomendado en Windows porque no depende de
Git Bash ni de `du`/`zip`:

```bash
# multiplataforma (stdlib), desde audit-engine/
../.venv/Scripts/python.exe scripts/build_layer.py
# o con un intérprete puntual (no hace falta que sea 3.12: pip resuelve para 3.12 igual)
python scripts/build_layer.py --python C:/Users/<usuario>/AppData/Local/Programs/Python/Python312/python.exe

# alternativa bash
./scripts/build_layer.sh
```

Ambos usan `pip install --platform manylinux2014_x86_64 --only-binary=:all:
--python-version 3.12 --implementation cp --target <tmp>/python -r
scripts/layer-requirements.txt` y empaquetan `python/` en la raíz del zip
(layout que exige Lambda). El script `.py` verifica al final que existan
`python/pypdf/__init__.py`, `python/docx/__init__.py` y
`python/lxml/__init__.py`, y que **no** haya `boto3`/`botocore` dentro (el
runtime python3.12 de Lambda ya los provee; `layer-requirements.txt` no los
lista ni los arrastra como transitivas). Resultado típico: ~5.5 MiB, ~370
entradas. `layers/` está ignorado por Git: se regenera en cada máquina y en
el job `terraform` de CI antes de `terraform validate`.

## 8. Evals (offline / live)

```bash
../.venv/Scripts/python.exe evals/run_evals.py --mode offline   # sin red; también corre dentro de pytest
```

Métricas, modo live, re-grabado de fixtures y qué citar en la tesis: ver
`evals/README.md`.

## 9. CI (GitHub Actions)

`.github/workflows/ci.yml` corre en cada push/PR, en `ubuntu-latest` con
Python 3.12: `lambda` (ruff + pytest), `api` (pytest), `desktop` (pytest
con Qt offscreen), `terraform` (build del layer + `fmt -check` + `init
-backend=false` + `validate` + checkov en modo `soft_fail`) y
`evals-offline`. Son las mismas órdenes de este documento; si pasan acá,
pasan en CI.
