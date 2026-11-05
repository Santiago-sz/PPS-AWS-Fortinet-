# 02 — Paso a paso: despliegue y prueba de punta a punta (Windows)

Runbook numerado y copiable. Salvo indicación contraria, los comandos se
ejecutan en **PowerShell**; cuando la sintaxis difiere se incluye la variante
**Git Bash**. Nada de lo que sigue fue ejecutado por el autor de este documento
contra AWS: los comandos `terraform apply` y `aws` mutantes los ejecuta el
dueño de la cuenta.

Convenciones:

- `<...>` = valor a reemplazar. Nunca pegar tokens ni claves en archivos del repo.
- Raíz del repo: `C:\Users\santi\dev\PPS-AWS-Fortinet-`. Pipeline: `audit-pipeline\`.
- Perfil AWS: `pps-tesis`. Cuenta `656051538542`. Región `us-east-1`.

---

## 0. Prerrequisitos

| Herramienta | Ubicación / versión | Verificar |
|---|---|---|
| Python 3.12 | `C:\Users\santi\AppData\Local\Programs\Python\Python312\python.exe` | `& "C:\Users\santi\AppData\Local\Programs\Python\Python312\python.exe" --version` |
| Terraform 1.15.9 | `C:\Users\santi\bin\terraform.exe` (en PATH) | `terraform version` |
| AWS CLI v2 | instalación estándar | `aws --version` |
| Git | Git for Windows | `git --version` |
| draw.io desktop (opcional) | `C:\Program Files\draw.io\draw.io.exe` | abrir `docs\diagrams\*.drawio` |
| Word o LibreOffice (opcional) | para convertir `.md` → PDF/DOCX de prueba | — |

---

## 1. Clonar fuera de Google Drive

Google Drive Desktop inyecta `desktop.ini` dentro de `.git` y toca los
binarios de providers de Terraform, lo que corrompe el checksum de
`.terraform.lock.hcl` (`missing or corrupted provider plugins`) y ha roto
`git fetch` en el pasado. Por eso el clon de trabajo vive en `C:\Users\santi\dev`.
Las copias bajo `G:\Mi unidad\TESIS\PPS prueba\` **quedaron obsoletas** (no
contienen el trabajo de 2026-11-04): no editar ni correr nada desde ahí.

```powershell
mkdir C:\Users\santi\dev -ErrorAction SilentlyContinue
cd C:\Users\santi\dev
git clone https://github.com/Santiago-sz/PPS-AWS-Fortinet-.git
cd PPS-AWS-Fortinet-
git status --short     # debe listar los cambios sin commitear de los Work Units 1-3
```

Nota: el clon actual tiene cambios sin commitear (ver sección 13). Si se vuelve
a clonar desde GitHub se obtiene `829c101` **sin** esos cambios.

---

## 2. Entorno virtual y tests

```powershell
cd C:\Users\santi\dev\PPS-AWS-Fortinet-
& "C:\Users\santi\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
cd audit-pipeline
..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\.venv\Scripts\python.exe -m pip install -r lambda\requirements.txt
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Resultado esperado en Windows: **275 passed, 1 skipped** (el skip es
`test_sandbox.py::TestWallClockBudgetViaSignalBackstop`: `signal.setitimer`
no existe en Windows; en Linux/CI corre y da 276 passed).

Lint y evals offline (sin red):

```powershell
..\.venv\Scripts\python.exe -m ruff check lambda/ evals/ scripts/build_layer.py
..\.venv\Scripts\python.exe -m ruff format --check lambda/ evals/ scripts/build_layer.py
$env:PYTHONUTF8 = "1"
..\.venv\Scripts\python.exe evals\run_evals.py --mode offline
```

API local y app de escritorio (desde la raíz del repo):

```powershell
cd C:\Users\santi\dev\PPS-AWS-Fortinet-
.\.venv\Scripts\python.exe -m pip install -e "audit-pipeline/api[dev]"
.\.venv\Scripts\python.exe -m pip install -e "desktop[dev]"
cd audit-pipeline\api
..\..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider      # 30 passed
cd ..\..\desktop
$env:QT_QPA_PLATFORM = "offscreen"
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider         # 45 passed
Remove-Item Env:QT_QPA_PLATFORM
```

Git Bash: reemplazar `..\.venv\Scripts\python.exe` por `../.venv/Scripts/python.exe`
y `$env:X = "v"` por `export X=v`.

---

## 3. Perfil AWS `pps-tesis`

Credenciales programáticas del usuario IAM `SantiUsuarioDePrueba1`
(AdministratorAccess en la cuenta de prueba). No pegar los valores en ningún
archivo del repositorio.

```powershell
aws configure set aws_access_key_id     <ACCESS_KEY_ID>     --profile pps-tesis
aws configure set aws_secret_access_key <SECRET_ACCESS_KEY> --profile pps-tesis
aws configure set region us-east-1 --profile pps-tesis
aws configure set output json      --profile pps-tesis
aws sts get-caller-identity --profile pps-tesis
```

`get-caller-identity` debe devolver `"Account": "656051538542"`.

Para el resto del runbook:

```powershell
$env:AWS_PROFILE = "pps-tesis"      # PowerShell
```

```bash
export AWS_PROFILE=pps-tesis        # Git Bash
```

---

## 4. Amazon Bedrock: acceso al modelo y cuota

### 4.1 Formulario de caso de uso (ya enviado para esta cuenta)

El acceso a los modelos Anthropic exige un formulario de caso de uso por
cuenta. **Para `656051538542` ya fue enviado y aceptado**; no repetirlo salvo
que se use otra cuenta. Se puede hacer desde la consola (Bedrock → Model
access) o por CLI:

```powershell
aws bedrock put-use-case-for-model-access --region us-east-1 --form-data fileb://use-case.json
```

Observaciones sobre `--form-data`: es un blob (`fileb://` evita tener que
codificar en base64 a mano); la referencia de la CLI **no documenta** el
esquema del JSON. Al enviarlo desde esta cuenta, el campo `intendedUsers`
rechazó texto libre y exigió un **código numérico** (como string), no una
descripción. Si hay que repetirlo, usar `--generate-cli-skeleton input` y
comparar con el formulario de la consola.

### 4.2 Verificar el perfil de inferencia

```powershell
aws bedrock list-inference-profiles --region us-east-1 `
  --query "inferenceProfileSummaries[?inferenceProfileId=='us.anthropic.claude-sonnet-4-6'].status"
```

Debe devolver `["ACTIVE"]`. `claude-sonnet-5-5` **no está disponible** para
esta cuenta (ver `05-decisiones.md`).

### 4.3 BLOQUEO CONOCIDO: cuota aplicada = 0

Las cuentas nuevas reciben cuota aplicada 0 para los modelos Anthropic. El
síntoma en el generador es `ThrottlingException: Too many tokens per day`
(aunque el perfil esté ACTIVE y la IAM sea correcta). Verificación:

```powershell
aws service-quotas list-service-quotas --service-code bedrock --region us-east-1 `
  --query "Quotas[?QuotaCode=='L-15B8E632' || QuotaCode=='L-00FF3314'].[QuotaCode,QuotaName,Value]" `
  --output table
```

- `L-15B8E632` = tokens por minuto (On-demand InvokeModel) para Claude Sonnet 4.6 cross-region.
- `L-00FF3314` = requests por minuto para el mismo modelo.

Solución: pedir el aumento en la **consola de Service Quotas** (Amazon
Bedrock → buscar el modelo → *Request increase at account level*) o abrir un
caso de AWS Support. La CLI
(`aws service-quotas request-service-quota-increase --service-code bedrock --quota-code L-15B8E632 --desired-value <N>`)
rechaza valores por debajo del default, así que no sirve para salir de 0.

Mientras la cuota siga en 0, el pipeline igualmente se puede probar: el
generador termina en `status=could_not_audit` con
`failure_reason=ClaudeCallError:ThrottlingException: ...`, escribe
`reports/{run_id}/report.{md,json}` y el evento `generator_result`. Eso valida
el disparo S3 → Lambda, IAM, layer, escritura en S3 y `pps-api aws sync`.

---

## 5. Construir el Lambda Layer

Prerrequisito de `terraform validate/plan/apply` (el recurso
`aws_lambda_layer_version.doc_parsers` calcula `filebase64sha256()` sobre el zip).

```powershell
cd C:\Users\santi\dev\PPS-AWS-Fortinet-\audit-pipeline
..\.venv\Scripts\python.exe scripts\build_layer.py
```

Salida esperada: `layers\pps-doc-parsers.zip` (~5.5 MiB) con `python/pypdf`,
`python/docx`, `python/lxml` y sin `boto3`. `layers/` está ignorado por Git.

---

## 6. Terraform: tfvars, init, plan, apply

### 6.1 `terraform.tfvars`

```powershell
cd C:\Users\santi\dev\PPS-AWS-Fortinet-\audit-pipeline\terraform
Copy-Item terraform.tfvars.example terraform.tfvars
notepad terraform.tfvars
```

Completar (el archivo está ignorado por Git):

| Variable | Valor para la prueba | Comentario |
|---|---|---|
| `notification_email` | correo que recibirá reportes y alarmas | Obligatoria. Confirmar la suscripción SNS después del apply. |
| `fortigate_host` | IP/hostname del FortiGate (HTTPS/443) | Obligatoria. Si todavía no hay FortiGate, poner un placeholder sintáctico (p. ej. `203.0.113.45`): el generador funciona igual y el executor reportará `could_not_audit` / hallazgos `indeterminate`. |
| `bedrock_model_id` | `us.anthropic.claude-sonnet-4-6` | Único perfil ACTIVE en la cuenta. |
| `auto_execute` | `true` para la primera prueba; `false` para el modo aprobación (sección 10) | Se inyecta como `AUTO_EXECUTE`. |
| `executor_subnet_ids` / `executor_security_group_ids` | `[]` / `[]` salvo FortiGate por IP privada | Ambas vacías o ambas con valores (precondición en `lambda.tf`). Ver `06-conexion-fortigate.md`. |
| `enable_bedrock_invocation_logging` | `true` | Configuración **única por cuenta/región**; en esta cuenta no existía antes, así que no pisa nada. |

### 6.2 `TF_DATA_DIR` fuera del árbol + init/plan/apply

PowerShell:

```powershell
$env:AWS_PROFILE = "pps-tesis"
$env:TF_DATA_DIR = "C:\Users\santi\.terraform-data\pps-audit-pipeline"
New-Item -ItemType Directory -Force $env:TF_DATA_DIR | Out-Null
cd C:\Users\santi\dev\PPS-AWS-Fortinet-\audit-pipeline\terraform
terraform fmt -check -recursive
terraform init -input=false
terraform validate
terraform plan -out tfplan
terraform apply tfplan
```

Git Bash:

```bash
export AWS_PROFILE=pps-tesis
export TF_DATA_DIR="C:/Users/santi/.terraform-data/pps-audit-pipeline"
mkdir -p "$TF_DATA_DIR"
cd /c/Users/santi/dev/PPS-AWS-Fortinet-/audit-pipeline/terraform
terraform fmt -check -recursive && terraform init -input=false && terraform validate
terraform plan -out tfplan && terraform apply tfplan
```

Notas:

- El estado es local (`terraform.tfstate` en este directorio, ignorado por
  Git). No perderlo: sin él, el próximo apply intentará recrear recursos con
  nombres ya tomados.
- `tfplan` es un binario que puede contener valores de variables: no
  commitearlo (hoy aparece como archivo sin seguimiento; conviene borrarlo o
  agregarlo a `.gitignore`).
- Al terminar, `terraform output next_steps` repite el checklist post-deploy;
  `terraform output` muestra los nombres reales (`policies_bucket`,
  `reports_bucket`, `generator_function_name`, `executor_function_name`,
  `fortigate_secret_arn`, `model_invocation_log_group`, `dead_letter_queue_urls`).

---

## 7. Post-apply

### 7.1 Confirmar la suscripción SNS

Abrir el correo de `notification_email` y hacer clic en *Confirm
subscription*. Verificar:

```powershell
aws sns list-subscriptions-by-topic --topic-arn (terraform output -raw notifications_topic_arn) --region us-east-1
```

`SubscriptionArn` debe ser un ARN, no `PendingConfirmation`.

### 7.2 Cargar el token del FortiGate

Terraform creó el secret con un placeholder y `ignore_changes`; el valor real
se carga una vez por fuera de Terraform (cómo generar el token: `06-conexion-fortigate.md`).

```powershell
aws secretsmanager put-secret-value `
  --secret-id (terraform output -raw fortigate_secret_arn) `
  --secret-string '{"token":"<TOKEN_REAL>","host":"<IP_O_HOSTNAME>"}' `
  --region us-east-1
```

Git Bash: igual, con `\` como continuación de línea y
`$(terraform output -raw fortigate_secret_arn)`.

El campo `host` dentro del secret es opcional y **no** reemplaza a
`FORTIGATE_HOST` (variable de entorno del executor, definida por
`var.fortigate_host`). El formato aceptado es `{"token": "<string no vacío>"}`;
un placeholder `REEMPLAZAR_CON_...` o JSON inválido hace fallar el executor
sin volcar el contenido del secret al log.

---

## 8. Conectar el FortiGate

Ver `06-conexion-fortigate.md`: perfil de acceso de solo lectura, usuario
REST API con trusted hosts, generación del token, y las tres opciones de
conectividad (VPN site-to-site + executor en VPC, FortiGate VM en AWS, IP
pública restringida). Hoy **no existe** ningún FortiGate ni VPN en la cuenta;
la prueba de la sección 9 se puede hacer igualmente y el resultado esperado
del executor será `could_not_audit`/`indeterminate` hasta que haya un equipo
alcanzable.

---

## 9. Prueba de punta a punta

### 9.1 Preparar una normativa de prueba

Opción recomendada: convertir `audit-pipeline\evals\policies\politica-acceso-administrativo.md`
(normativa sintética de 6 secciones: trusted hosts, bloqueo de admins,
timeout de inactividad, HTTPS obligatorio) a PDF o DOCX:

1. Abrir el `.md` en Word (Archivo → Abrir, tipo "Todos los archivos"), o
   copiar el texto en un documento nuevo conservando los títulos `## N.` como
   estilos *Título 2* (con DOCX, el chunker usa esos estilos para delimitar
   cláusulas; con PDF usa la numeración `N.M`).
2. Archivo → *Guardar como* → `politica-acceso-administrativo.pdf` (o `.docx`).

También sirve cualquier PDF/DOCX real con texto seleccionable (no escaneado).
Un PDF escaneado termina en `could_not_audit` / `extraction_error:no_text_layer`.

### 9.2 Camino A — prueba de cableado directa con `aws s3 cp`

Útil para validar S3 → Lambda → Bedrock → S3 sin la GUI. Estos runs **no**
aparecerán en `pps-api aws sync` (el sync solo correlaciona auditorías
enviadas desde la API local, por `policy_key`).

```powershell
$env:AWS_PROFILE = "pps-tesis"
cd C:\Users\santi\dev\PPS-AWS-Fortinet-\audit-pipeline\terraform
$POLICIES = terraform output -raw policies_bucket
$REPORTS  = terraform output -raw reports_bucket
$GEN      = terraform output -raw generator_function_name
$EXEC     = terraform output -raw executor_function_name

aws s3 cp C:\ruta\politica-acceso-administrativo.pdf "s3://$POLICIES/policies/politica-acceso-administrativo.pdf"
aws logs tail "/aws/lambda/$GEN" --follow --region us-east-1
```

En otra terminal, cuando aparezca `generator_result`:

```powershell
aws logs tail "/aws/lambda/$EXEC" --since 10m --region us-east-1
aws s3 ls "s3://$REPORTS/artifacts/" --recursive
aws s3 ls "s3://$REPORTS/reports/"   --recursive
aws s3 cp "s3://$REPORTS/reports/<run_id>/report.md" -     # imprime el reporte
aws s3 cp "s3://$REPORTS/artifacts/<run_id>/manifest.json" -
```

Git Bash: `POLICIES=$(terraform output -raw policies_bucket)` y `"$POLICIES"`.

### 9.3 Camino B — flujo completo con la app de escritorio (el de la tesis)

1. `.env` en la raíz del repo (copiar `.env.example`; ignorado por Git):

   ```dotenv
   AWS_PROFILE=pps-tesis
   AWS_REGION=us-east-1
   PPS_POLICIES_BUCKET=<policies_bucket>
   PPS_REPORTS_BUCKET=<reports_bucket>
   PPS_EXECUTOR_FUNCTION=<executor_function_name>
   ```

   Dejar vacías las tres claves `AWS_ACCESS_KEY_*`/`AWS_SESSION_TOKEN` para
   usar el perfil. `PPS_EXECUTOR_FUNCTION` solo lo usa `aws approve`; la
   línea `PPS_EXECUTOR_FUNCTION=pps-prod-audit-executor` debe agregarse a
   mano al `.env` (la plantilla `.env.example` puede ir atrasada; el lector
   la acepta y `audit-pipeline/api/README.md` muestra el bloque completo).

2. Terminal 1 — API local (escucha solo en `127.0.0.1:8765`):

   ```powershell
   cd C:\Users\santi\dev\PPS-AWS-Fortinet-
   .\.venv\Scripts\pps-api serve
   ```

   Equivalente sin el entry point: `.\.venv\Scripts\python.exe audit-pipeline\api\launch.py serve`.

3. Terminal 2 — app de escritorio:

   ```powershell
   cd C:\Users\santi\dev\PPS-AWS-Fortinet-
   .\.venv\Scripts\python.exe desktop\launch.py
   ```

   En **Configuración → API local de desarrollo**: URL `http://127.0.0.1:8765`
   → *Conectar API local*. En **Políticas**: cargar el PDF/DOCX. La API lo
   valida y deja la auditoría en cola (no llama a AWS).

4. Terminal 3 — enviar y sincronizar:

   ```powershell
   cd C:\Users\santi\dev\PPS-AWS-Fortinet-
   .\.venv\Scripts\pps-api --env-file .env aws dispatch     # sube policies/{audit_id}.pdf
   aws logs tail "/aws/lambda/<generator_function_name>" --follow --region us-east-1 --profile pps-tesis
   # cuando el executor termine (o el generador falle):
   .\.venv\Scripts\pps-api --env-file .env aws sync
   ```

   `aws sync` imprime `Auditorías procesadas: N`. Repetirlo mientras N sea 0
   y los logs no muestren todavía `executor_result`.

5. Volver a la app: **Resumen** / **Resultados** muestran el reporte. Cada
   hallazgo cita la cláusula (`heading_path`, página, cita textual) y, si es
   `fail`/`indeterminate` con propuesta, el bloque **Remediación propuesta**
   con la leyenda de que nada se aplicó. Exportar JSON/Markdown desde la GUI.

### 9.4 Qué esperar según el estado

| Situación | Log del generador | Log del executor | `report.json` | GUI |
|---|---|---|---|---|
| Cuota Bedrock en 0 (estado actual) | `llm_call` con `error: ThrottlingException...`, `generator_result status=could_not_audit` | no se invoca | `status=could_not_audit`, `failure_reason=ClaudeCallError:ThrottlingException: ...` | "No se pudo auditar" |
| Cuota OK, FortiGate inalcanzable | `generation_result success=true`, `generator_result status=invoked` | `fgt.get` devuelve `None` por endpoint (`No se puede conectar al FortiGate`), `executor_result status=completed` | hallazgos mayormente `indeterminate` con evidencia "sin datos" | "Lista", cumplimiento "Sin datos suficientes" |
| Todo operativo | idem | `executor_result status=completed`, `findings_count=N` | `completed`, `remediation_count` | tabla con pass/fail y remediaciones |
| Script excede presupuesto | idem | `Sandbox terminado por presupuesto`, `status=truncated` | `truncated=true`, hallazgos parciales | "Parcial · límite alcanzado" |
| Normativa sin controles verificables | `generator_result status=no_verifiable_controls` | no se invoca | `could_not_audit` / `no_verifiable_controls` | "Sin controles verificables" |
| `auto_execute=false` | `awaiting_approval` + `generator_result status=awaiting_approval` | solo tras `approve` | ninguno hasta aprobar | "Pendiente de aprobación" |

Métricas EMF en CloudWatch → namespace `PPS/AuditPipeline`
(`LlmInputTokens`, `LlmOutputTokens`, `LlmLatencyMs` por `Stage`;
`GenerationAttempts`, `GenerationFirstAttemptPass`). Prompts y respuestas
completas: log group `/aws/bedrock/pps-prod-model-invocations`.

---

## 10. Modo aprobación humana

1. En `terraform.tfvars`: `auto_execute = false` → `terraform plan -out tfplan` → `terraform apply tfplan`
   (solo cambia la variable de entorno `AUTO_EXECUTE` del generador).
2. Cargar y despachar como en 9.3. El generador deja `artifacts/{run_id}/`
   firmado y **no** invoca al executor.
3. Revisar y aprobar:

   ```powershell
   .\.venv\Scripts\pps-api --env-file .env aws list-pending            # run_ids con manifest y sin reporte
   aws s3 cp "s3://<reports_bucket>/artifacts/<run_id>/manifest.json" - --profile pps-tesis   # controles + remediaciones propuestas
   aws s3 cp "s3://<reports_bucket>/artifacts/<run_id>/script.py" -    --profile pps-tesis   # script a ejecutar
   .\.venv\Scripts\pps-api --env-file .env aws approve <run_id>        # usa PPS_EXECUTOR_FUNCTION; o --executor-function <nombre|arn>
   .\.venv\Scripts\pps-api --env-file .env aws sync
   ```

`approve` exige `run_id`, `script_key` bajo `artifacts/{run_id}/` y
`script_sha256` de 64 hex en el manifest, rechaza runs que ya tienen
`reports/{run_id}/report.json` y hace **una** invocación asíncrona sin
reintentos (repetir el comando duplicaría la ejecución). El executor recalcula
el hash antes de ejecutar.

---

## 11. Evals del generador

```powershell
cd C:\Users\santi\dev\PPS-AWS-Fortinet-\audit-pipeline
$env:PYTHONUTF8 = "1"
..\.venv\Scripts\python.exe evals\run_evals.py --mode offline                 # sin red; lo que corre CI
$env:AWS_PROFILE = "pps-tesis"; $env:AWS_REGION = "us-east-1"
..\.venv\Scripts\python.exe evals\run_evals.py --mode live                    # Bedrock real (requiere cuota > 0)
..\.venv\Scripts\python.exe evals\run_evals.py --mode live --record           # re-graba evals/recorded/*.json
..\.venv\Scripts\python.exe evals\run_evals.py --mode live --policy politica-contrasenas
```

Salida: tabla Markdown + `evals\results\<timestamp>-<modo>.json`; código 1
si alguna métrica queda bajo `evals\thresholds.json`. Última corrida offline:

| policy | status | 1st-pass | attempts | checks | recall | ep-prec | remed | tok in/out |
|---|---|---|---|---|---|---|---|---|
| politica-acceso-administrativo | ok | no | 2 | 5 | 1.00 | 1.00 | 1.00 | 8070/3330 |
| politica-contrasenas | ok | yes | 1 | 5 | 1.00 | 1.00 | 1.00 | 4770/2150 |
| politica-registro-y-ntp | ok | yes | 1 | 4 | 1.00 | 1.00 | 1.00 | 4700/1740 |
| **overall** | success 1.00 | 0.67 | | | 1.00 | 1.00 | 1.00 | 17540/7220 |

Con la cuota en 0, `--mode live` falla con `ThrottlingException` en la primera llamada.

---

## 12. Troubleshooting

| Síntoma | Causa probable | Acción |
|---|---|---|
| `AccessDeniedException` en `llm_call` | Acceso al modelo no habilitado o perfil de inferencia inexistente en la región | §4.1 y §4.2; comprobar `BEDROCK_MODEL_ID` en la Lambda y que IAM incluya `inference-profile/*` (ya lo hace). |
| `ThrottlingException: Too many tokens per day` | Cuota aplicada 0 (cuenta nueva) | §4.3: pedir aumento de `L-15B8E632` / `L-00FF3314` en Service Quotas o Support. El run termina `could_not_audit`; no es un bug del código. |
| `terraform validate` falla con `no file exists` sobre `layers/pps-doc-parsers.zip` | Layer no construido | §5. |
| `missing or corrupted provider plugins` | `.terraform/` dentro de Google Drive o antivirus | `TF_DATA_DIR` fuera del árbol (§6.2); borrar `.terraform/` local y `init` de nuevo. |
| `git fetch`/`status` raro, archivos `desktop.ini` | Repositorio dentro de Google Drive | Trabajar solo en `C:\Users\santi\dev\...` (§1). `desktop.ini` ya está en `.gitignore`. |
| Executor: `HTTP 401` al consultar FortiGate | Token inválido/expirado o secret con placeholder | Regenerar token (`06-conexion-fortigate.md`), `put-secret-value` (§7.2). |
| Executor: `HTTP 403` | Perfil de acceso del usuario API sin permiso de lectura sobre ese árbol | Revisar `accprofile` (todas las secciones en `read`). |
| Executor: `No se puede conectar al FortiGate` / timeout 15 s | Sin ruta (Lambda fuera de VPC y FortiGate privado), SG, trusted hosts, o `FORTIGATE_HOST` placeholder | `06-conexion-fortigate.md`; recordar que una Lambda fuera de VPC no tiene IP de egreso fija. |
| Certificado autofirmado: `CERTIFICATE_VERIFY_FAILED` | `FORTIGATE_VERIFY_SSL` por defecto `true`; Terraform no expone esa variable | Instalar un certificado válido en el FortiGate, o agregar `FORTIGATE_VERIFY_SSL="false"` al bloque `environment` del executor en `lambda.tf` (cambio de código pendiente, solo para laboratorio). |
| No llegan correos | Suscripción SNS sin confirmar | §7.1. |
| `pps-api aws sync` devuelve `0` aunque hay `report.json` | El sync solo mira auditorías locales en `dispatch IN ('sending','sent')` y las correlaciona por `policy_key = policies/{audit_id}.<ext>`; una subida manual con `aws s3 cp` nunca coincide | Usar el camino B; o leer el reporte directo desde S3; o `pps-api import-result <audit_id> manifest.json report.json` si el documento es el mismo (verifica SHA-256). |
| `sync` marca `conflict` | Dos `report.json` con el mismo `policy_key` y distinto `run_id` (evento S3 duplicado) | Elegir uno y adjuntarlo con `import-result`. |
| `approve` → `run_already_reported` | El run ya tiene `reports/{run_id}/report.json` | Nada que aprobar; correr `sync`. |
| pytest: `1 skipped` | `SIGALRM` inexistente en Windows | Esperado. En Linux/CI corre (276 passed). |
| checkov `UnicodeDecodeError` | cp1252 por defecto | `$env:PYTHONUTF8 = "1"`. |
| Alarma `*-dlq-messages` | Lambda agotó reintentos asíncronos (timeout, excepción no controlada) | `aws sqs receive-message --queue-url <url>` (ver `terraform output dead_letter_queue_urls`), revisar logs, re-invocar con el mismo payload. |

---

## 13. Publicar los cambios (no ejecutado)

El orquestador **no** commiteó nada. Los Work Units 1-4 están en el árbol de
trabajo (`git status --short` lista ~45 archivos modificados y ~20 nuevos,
incluido `docs/`). Antes de commitear: borrar o ignorar
`audit-pipeline/terraform/tfplan` y confirmar que no haya `.tfvars`, `.env`
ni `layers/` en el índice (`git status` no debe listarlos).

```powershell
cd C:\Users\santi\dev\PPS-AWS-Fortinet-
git status --short
git add .github AGENTS.md CLAUDE.md README.md docs lambda/README-LEGACY.md terraform/README-LEGACY.md
git add audit-pipeline desktop .gitignore
git reset -q audit-pipeline/terraform/tfplan        # si quedó agregado
git commit -m "feat: pipeline policy-driven sobre Bedrock, harness de evals, hardening IaC y documentación de Fase 1"
git push origin master
```

Sugerencia: partirlo en commits por unidad de trabajo (lambda + tests;
terraform; api + desktop; docs + diagramas) con mensajes convencionales
(`feat:`, `fix:`, `docs:`, `chore:`). Verificar luego que el workflow `CI`
de GitHub Actions quede en verde (jobs `lambda`, `api`, `desktop`,
`terraform`, `evals-offline`).
