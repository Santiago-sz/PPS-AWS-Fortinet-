# Puesta en marcha desde cero

Fecha: 2026-11-22. Documento de entrada para quien llega a este repositorio
sin contexto previo: un agente de código en otra PC con Windows, o cualquiera
de los dos autores de la tesis. Lleva de un clon nuevo a una demostración
funcionando y deja claro qué falta.

**Cómo leerlo.** Seguir las secciones en orden. Cada paso tiene un comando para
copiar, el resultado esperado y qué hacer si difiere. Las marcas indican cuánto
confiar en cada paso:

| Marca | Significado |
|---|---|
| **[V]** | Ejecutado el 2026-11-22 en la PC original (Windows 11, Windows PowerShell 5.1, Python 3.12.10, AWS CLI 2.36.25) con el resultado indicado |
| **[I]** | Informado por los autores o tomado de otro documento del repositorio; no se volvió a ejecutar al escribir esta guía |
| **[NV]** | No verificado. Seguirlo con cuidado y corregir esta guía si no funciona |

## Camino rápido

1. Clonar **fuera de cualquier carpeta sincronizada** (Drive, OneDrive) y crear
   el entorno virtual: [sección 3](#3-instalación-desde-cero-en-windows).
2. Configurar el perfil de AWS y comprobar que los recursos existen, solo con
   lecturas: [sección 4](#4-acceso-a-aws).
3. Correr los tests: [sección 5](#5-tests-y-linters). Resultado esperado: 572,
   37 y 49 aprobados.
4. Hacer la demostración que no necesita FortiGate:
   [sección 6](#6-guion-de-demostración).
5. Leer el estado y lo que sigue: [sección 9](#9-estado-actual-defectos-conocidos-y-próximos-pasos).

Antes de modificar algo, leer [AGENTS.md](../../AGENTS.md) completo y la
[sección 11](#11-reglas-para-un-agente).

## 1. Qué es el producto

PostureGuard convierte una normativa de seguridad (PDF o DOCX) en una auditoría
automática y **de solo lectura** de un firewall FortiGate. El resultado es un
reporte con un hallazgo por control, que cita la cláusula de la normativa y
propone una remediación para que la revise una persona. El sistema nunca
modifica el FortiGate.

```text
 normativa.pdf
      |  (subida a S3: bucket de políticas, prefijo policies/)
      v
 Lambda policy_generator  ---- consulta ---->  Base de conocimientos (Bedrock)
      |  extrae texto, identifica controles,          documentación técnica
      |  genera un script y lo valida                 de referencia (RAG)
      v
 artifacts/<run_id>/manifest.json + script.py   (bucket de reportes)
      |
      v
 Lambda audit_executor      o      ejecución local (scripts/run_executor_local.py)
      |  verifica el hash, vuelve a validar,
      |  ejecuta el script en un sandbox
      v
 FortiGate (solo GET sobre su API REST)
      |
      v
 report.json + report.md  --->  API local  --->  aplicación de escritorio
```

Detalle de la arquitectura: [architecture.md](architecture.md) y
[el README de la raíz](../../README.md).

### Glosario

| Término | Significado en este proyecto |
|---|---|
| Normativa | Documento PDF o DOCX con las exigencias de seguridad que se quieren comprobar |
| Corrida (`run`) | Una generación identificada por un `run_id` de 32 caracteres hexadecimales, con sus artefactos y su reporte |
| Manifest | `manifest.json`: lista de controles de la corrida, con la cláusula citada, los endpoints que consulta cada uno, la remediación propuesta, el hash del script y las referencias de la base de conocimientos |
| Script | Código Python generado por el modelo para esa normativa. Solo puede llamar a `fgt.get(...)` y `report.finding(...)` |
| Validador | Lista de permitidos sobre el árbol sintáctico del script: sin `import`, sin escritura, sin reflexión (`audit-engine/contracts/script_validator.py`) |
| Sandbox | Entorno restringido donde se ejecuta el script, con límites de tiempo y de llamadas (`audit-engine/executor/sandbox.py`) |
| Toolkit | Los dos objetos que el script recibe: `fgt` para leer y `report` para registrar hallazgos (`audit-engine/executor/toolkit.py`) |
| Base de conocimientos (RAG) | Base administrada de Amazon Bedrock con documentación técnica. El generador recupera fragmentos y los usa como referencia al escribir el script |
| Hallazgo | Resultado de un control: `pass`, `fail`, `not_applicable` o `indeterminate`, con su evidencia |
| Indeterminado | El control no pudo evaluarse con los datos disponibles. No es aprobado ni fallido |

## 2. Qué viaja con git y qué no

**Con el clon se obtiene** el código, los tests, la infraestructura como código
y esta documentación. **No se obtiene nada de lo siguiente**, y sin ello algunas
partes de la demostración no pueden mostrarse.

| Qué | Para qué sirve | Dónde está | Cómo recuperarlo en otra PC |
|---|---|---|---|
| Credenciales de AWS | Todo lo que consulta AWS | En la PC de cada autor, fuera del repositorio | Las entrega el dueño de la cuenta; configurar un perfil ([sección 4](#4-acceso-a-aws)). Nunca en el repositorio |
| Token del FortiGate | Ejecución contra un equipo | Solo en la sesión de quien ejecuta, o en Secrets Manager | Generarlo en el equipo; ver [la guía de ejecución local](local-executor-run.md) |
| Estado y variables de Terraform (`terraform.tfstate`, `terraform.tfvars`) | Cambiar la infraestructura desplegada | En la PC desde la que se desplegó, dentro de `infrastructure/pipeline/` y de `infrastructure/knowledge-base/` (ignorados por git) [I] | Copiarlos por un canal seguro. **Sin ellos la infraestructura desplegada puede usarse, pero no debe volver a aplicarse**: un `apply` sin el estado intentaría crear todo de nuevo |
| Base de la aplicación (`.pps-api/development.sqlite3`) | Ver en la aplicación las dos corridas reales ya adjuntadas | PC original, raíz del clon (ignorada por git) | Copiarla a la misma ruta, o reconstruirla adjuntando los reportes ([sección 8](#8-ver-resultados-en-la-aplicación)). **Confidencial**: contiene configuración real de un equipo |
| `audit-engine/local-runs/` | Reportes de las dos ejecuciones reales y salidas del diagnóstico | PC original (ignorado por git) | Copiar la carpeta. **Confidencial: configuración real de un equipo. No incorporar a git ni compartir** |
| Archivo de la normativa usada (DA 641/2021, PDF) | Adjuntar un reporte en la aplicación; disparar una generación | PC original; el bucket de políticas tiene 4 objetos bajo `policies/` [V] y el manifest de cada corrida indica cuál usó en `policy_key` | `aws s3 cp "s3://$POLICIES/<policy_key>" <destino fuera del repositorio>` (solo lectura). Para adjuntar debe ser exactamente el mismo archivo |
| Carpeta del corpus de la base de conocimientos | Solo si hay que cambiar documentos | PC original y bucket de conocimiento | `aws s3 sync "s3://$KNOWLEDGE" <carpeta>` (solo lectura). No hace falta para usar la base |
| Evidencia de las pruebas: «PostureGuard - Evidencia primera prueba real.docx», «PostureGuard - Evidencia pruebas reales y base de conocimientos.docx» y la carpeta `PostureGuard-evidencia-capturas` | Material para el informe de la tesis | Escritorio de la PC original [I] | Copiarlos a mano. Pueden contener datos del equipo auditado |
| Entorno virtual `.venv/` y `audit-engine/layers/` | Ejecutar todo; construir el layer | Se regeneran | [Sección 3](#3-instalación-desde-cero-en-windows); el layer solo se necesita para validar Terraform |
| `audit-engine/evals/results/` | Resultados de las evaluaciones | Se regeneran | Volver a correr las evaluaciones |

La aplicación de escritorio propone guardar sus exportaciones como
`pps-reporte.json`. Si se guardan en la raíz del clon quedan ignoradas por git
(regla `/pps-reporte*.json`), pero contienen datos de reportes: no moverlas a
carpetas con seguimiento.

## 3. Instalación desde cero en Windows

Requisitos: Windows 10 u 11, Git, Python 3.12, AWS CLI v2. Terraform solo si se
va a validar o desplegar infraestructura.

### 3.1 Herramientas

```powershell
git --version
aws --version
py -3.12 --version
```

| Comando | Resultado esperado | Si difiere |
|---|---|---|
| `git --version` [V] | `git version 2.x` | Instalar Git para Windows |
| `aws --version` [V] | `aws-cli/2.x` | Instalar AWS CLI v2 |
| `py -3.12 --version` [NV] | `Python 3.12.x` | En la PC original ni `py` ni `python` están en el `PATH`; el intérprete está en `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. Usar esa ruta completa en lugar de `py -3.12` |

La API y la aplicación admiten Python 3.11 o superior; el motor y la CI usan
3.12. Usar 3.12 para todo.

### 3.2 Clonar fuera de carpetas sincronizadas

```powershell
cd C:\Users\<usuario>\dev
git clone https://github.com/Santiago-sz/PPS-AWS-Fortinet-.git
cd PPS-AWS-Fortinet-
git status --short --branch
```

Resultado esperado: `## master...origin/master` y ningún cambio pendiente. [NV]
para un clon nuevo; la URL sale de los enlaces de CI registrados en
[status.md](status.md).

Un clon dentro de Google Drive u otra carpeta sincronizada corrompe `.git` y los
binarios de los providers de Terraform. Es un problema que ya ocurrió.

### 3.3 Entorno virtual único

Un solo entorno, `.venv` en la raíz, sirve para el motor, la API y la
aplicación. Algunos manuales nombran `.venv-gui`: es el mismo entorno con otro
nombre; donde diga `.venv-gui`, usar `.venv`.

Desde la raíz del clon:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r audit-engine\requirements-dev.txt -r audit-engine\requirements.txt
.\.venv\Scripts\python.exe -m pip install -e "local-api[dev]" -e "gui[dev]"
.\.venv\Scripts\python.exe -m pip install "boto3==1.43.123"
```

El último comando va al final a propósito: `checkov` fija `boto3==1.35.49`, y
esa versión no conoce la API de bases de conocimiento administradas. Al
reinstalar `boto3` aparece un aviso de conflicto con `checkov`; es el esperado
(la CI hace lo mismo).

Verificación:

```powershell
.\.venv\Scripts\python.exe -c "import boto3, PySide6, moto, pytest, pypdf, docx; print(boto3.__version__)"
```

Resultado esperado: `1.43.123`.

Estado de la verificación: la resolución de dependencias de los comandos
tercero y cuarto se comprobó con `pip install --dry-run` en un entorno nuevo
[V]; la instalación real desde cero no se ejecutó [NV]. Las versiones
resultantes coinciden con las del entorno de la PC original (pytest 8.3.5,
ruff 0.11.2, moto 5.1.4, PySide6 6.11.2, checkov 3.2.379).

## 4. Acceso a AWS

La infraestructura ya está desplegada en una cuenta de AWS, región `us-east-1`,
con el prefijo `pps-prod`. Esta sección solo hace lecturas.

### 4.1 Configurar el perfil

El nombre de perfil usado hasta ahora es `pps-tesis`. Las claves las entrega el
dueño de la cuenta y se cargan de forma interactiva; no se escriben en ningún
archivo del repositorio ni en una conversación.

```powershell
aws configure --profile pps-tesis
```

Completar la clave de acceso, la clave secreta, la región `us-east-1` y el
formato `json`. [I]

### 4.2 Variables de la sesión

Ejecutar esto al abrir cada consola de PowerShell. Los identificadores se
obtienen de la cuenta en lugar de escribirse en la documentación.

```powershell
$env:AWS_PROFILE = "pps-tesis"
$env:AWS_DEFAULT_REGION = "us-east-1"
$ACCOUNT = aws sts get-caller-identity --query Account --output text
$POLICIES = "pps-prod-policies-$ACCOUNT"
$REPORTS = "pps-prod-reports-$ACCOUNT"
$KNOWLEDGE = "pps-prod-knowledge-$ACCOUNT"
$KB = aws bedrock-agent list-knowledge-bases --query "knowledgeBaseSummaries[?name=='pps-prod-knowledge-base'].knowledgeBaseId" --output text
$DS = aws bedrock-agent list-data-sources --knowledge-base-id $KB --query "dataSourceSummaries[0].dataSourceId" --output text
"$($ACCOUNT.Length) $($KB.Length)"
```

Resultado esperado de la última línea: `12 10` (largo del número de cuenta y
del identificador de la base). [V] Si aparece un error de credenciales, repetir
4.1. `boto3` lee `AWS_DEFAULT_REGION`, no `AWS_REGION`.

### 4.3 Comprobar que los recursos existen

```powershell
aws lambda list-functions --query "Functions[?starts_with(FunctionName,'pps-prod')].FunctionName" --output text
aws s3api list-buckets --query "Buckets[?starts_with(Name,'pps-prod')].Name" --output text
aws bedrock-agent get-knowledge-base --knowledge-base-id $KB --query "knowledgeBase.[name,status]" --output text
aws bedrock-agent list-ingestion-jobs --knowledge-base-id $KB --data-source-id $DS --query "ingestionJobSummaries[].[ingestionJobId,status]" --output text
aws lambda get-function-configuration --function-name pps-prod-policy-generator --query "Environment.Variables.[AUTO_EXECUTE,BEDROCK_MODEL_ID]" --output text
aws secretsmanager list-secrets --query "SecretList[?starts_with(Name,'pps-prod')].Name" --output text
```

| Comando | Resultado esperado [V] |
|---|---|
| `list-functions` | `pps-prod-policy-generator`, `pps-prod-assessor`, `pps-prod-audit-executor` |
| `list-buckets` | Tres buckets: `pps-prod-knowledge-…`, `pps-prod-policies-…`, `pps-prod-reports-…` |
| `get-knowledge-base` | `pps-prod-knowledge-base  ACTIVE` |
| `list-ingestion-jobs` | Dos trabajos en `COMPLETE` (`R4MQ9D7QQZ` y `L0GF2MB3YJ`) y uno en `STOPPED` |
| `get-function-configuration` | `true  us.anthropic.claude-sonnet-4-6` |
| `list-secrets` | `pps-prod-fortigate-token` |

**Si algún recurso no existe:** no desplegar por cuenta propia. El despliegue lo
hace el dueño de la cuenta con Terraform, en dos módulos y en este orden:
primero `infrastructure/knowledge-base`, después `infrastructure/pipeline`. Los
pasos están en [el README del módulo de la base](../../infrastructure/knowledge-base/README.md),
en [el resumen del RAG](rag/README.md) y en
[el paso a paso de despliegue](../base/02-paso-a-paso-despliegue-y-prueba.md)
(este último conserva rutas anteriores a la reorganización; ver
[repository-layout.md](repository-layout.md)). Un agente no ejecuta
`terraform plan` ni `apply`.

## 5. Tests y linters

Nada de esta sección usa red, AWS ni un FortiGate. Los resultados son los del
commit en que se escribió esta guía.

```powershell
cd audit-engine
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
..\.venv\Scripts\python.exe -m ruff check generator/ executor/ contracts/ legacy/ tests/ evals/ scripts/
..\.venv\Scripts\python.exe -m ruff format --check generator/ executor/ contracts/ legacy/ tests/ evals/ scripts/
..\.venv\Scripts\python.exe evals\run_evals.py --mode offline
..\.venv\Scripts\python.exe evals\run_evals.py --suite retrieval --mode offline
cd ..\local-api
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
cd ..\gui
$env:QT_QPA_PLATFORM = "offscreen"
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
..\.venv\Scripts\python.exe -m ruff check .
Remove-Item Env:QT_QPA_PLATFORM
cd ..
```

| Comprobación | Resultado esperado [V] |
|---|---|
| `pytest` en `audit-engine` | `572 passed, 1 skipped` |
| `ruff check` en `audit-engine` | `All checks passed!` |
| `ruff format --check` | `53 files already formatted` |
| Evaluaciones offline (ambas) | Código de salida 0 |
| `pytest` en `local-api` | `37 passed` |
| `pytest` en `gui` | `49 passed` |
| `ruff check` en `gui` | `All checks passed!` |

Los comandos se ejecutaron desde Git Bash con las mismas rutas; en PowerShell
son equivalentes. Quitar `QT_QPA_PLATFORM` al terminar: con esa variable la
aplicación abre sin ventana visible.

**Windows y Linux.** El test omitido en Windows es el del respaldo de tiempo por
señal del sandbox (`signal.setitimer` no existe en Windows). En Linux, que es
lo que usa la CI, ese test corre: se espera `573 passed` sin omitidos, valor
inferido y no observado para este commit.

Más detalle, Terraform y Checkov: [TESTING.md](../../audit-engine/TESTING.md).

## 6. Guion de demostración

Hay dos versiones. La primera puede hacerse hoy y no necesita un FortiGate. La
segunda es la demostración de la tesis y depende de un laboratorio que todavía
no existe.

**Qué cuesta y qué escribe en AWS**

| Paso | Escribe en AWS | Costo |
|---|---|---|
| 6.1 a 6.4 | No | Ninguno, salvo las consultas de 6.2: USD 1 cada 1.000 llamadas |
| 6.5 Generar una corrida nueva | **Sí** (sube un objeto, invoca dos Lambdas, escribe artefactos y un reporte) | **Tokens de Bedrock.** Lo decide el usuario |

### 6.1 La base de conocimientos en la consola

En la consola de AWS, región `us-east-1`: **Amazon Bedrock → Bases de
conocimiento → `pps-prod-knowledge-base`**. La vista general muestra «Almacén
vectorial administrado» y el origen de datos sincronizado. Con **Probar** y la
opción **Solo recuperación estándar** se escribe una consulta y se ven los
fragmentos recuperados con su documento de origen. [I]

### 6.2 La base de conocimientos por línea de comandos

Con las variables de 4.2:

```powershell
aws bedrock-agent-runtime retrieve --knowledge-base-id $KB --retrieval-query "text=password policy minimum length" --retrieval-configuration "managedSearchConfiguration={numberOfResults=3}" --query "retrievalResults[].[score,location.s3Location.uri]" --output text
```

Resultado esperado [V]: tres líneas, cada una con un puntaje entre 0 y 1 y la
dirección del documento de origen dentro del bucket de conocimiento (el
2026-11-22, tres fragmentos de la referencia de CLI de FortiOS 7.6.8).

Los parámetros van en sintaxis abreviada a propósito: Windows PowerShell quita
las comillas dobles de un JSON pasado en línea y el comando falla.

Para mostrar qué documentos tiene la base:

```powershell
aws s3 ls "s3://$KNOWLEDGE/" --recursive
```

Resultado esperado [V]: 26 objetos. Son los 24 documentos del
[manifiesto del corpus](rag/corpus.md) más dos archivos `.metadata.json` que
acompañan a dos documentos de Fortinet con su versión de FortiOS.

### 6.3 Los artefactos de una corrida ya generada

Corridas existentes: `9c1fa81e1a154d1fa510274997381280` (corpus anterior, 12
controles) y `dd1b2879454a4ddfb426c395481312c0` (corpus actual, 14 controles).

```powershell
$RUN = "dd1b2879454a4ddfb426c395481312c0"
$DEMO = "$env:TEMP\pps-demo"
New-Item -ItemType Directory -Force $DEMO | Out-Null
aws s3 ls "s3://$REPORTS/artifacts/$RUN/"
aws s3 cp "s3://$REPORTS/artifacts/$RUN/manifest.json" "$DEMO\manifest.json" --only-show-errors
aws s3 cp "s3://$REPORTS/artifacts/$RUN/script.py" "$DEMO\script.py" --only-show-errors
$m = Get-Content "$DEMO\manifest.json" -Raw -Encoding UTF8 | ConvertFrom-Json
"controles: $($m.checks.Count)  intentos: $($m.attempts)  modelo: $($m.model)"
$m.checks | Select-Object check_id, severity, @{n="endpoints";e={$_.endpoints -join ","}} | Format-Table -AutoSize
"controles con referencias: $($m.knowledge_base.controls_with_references) de $($m.knowledge_base.controls_total)"
notepad "$DEMO\script.py"
```

Resultado esperado [V]: `manifest.json` y `script.py` en el listado;
`controles: 14  intentos: 2  modelo: us.anthropic.claude-sonnet-4-6`; una tabla
de `chk-0001` a `chk-0014` con sus endpoints; y el script generado, de 320
líneas; y `controles con referencias: 14 de 14`.

Qué mostrar con esto: la normativa se convirtió en controles trazables (cada
uno con su cláusula en `clause_ref`), el modelo necesitó dos intentos porque el
validador rechazó el primero, y el script solo usa `fgt.get` y
`report.finding`. Los artefactos se descargan a `%TEMP%`, fuera del
repositorio.

El reporte que dejó la Lambda para esa corrida no tiene datos:

```powershell
aws s3 cp "s3://$REPORTS/reports/$RUN/report.json" "$DEMO\report-lambda.json" --only-show-errors
$r = Get-Content "$DEMO\report-lambda.json" -Raw -Encoding UTF8 | ConvertFrom-Json
"estado: $($r.status)  motivo: $($r.failure_reason)  hallazgos: $($r.findings.Count)"
```

Resultado esperado [V]: `estado: could_not_audit  motivo:
preparation_error:ValueError  hallazgos: 0`. Es correcto y conviene explicarlo:
la Lambda no tiene un FortiGate al que conectarse. El motivo indica que la
preparación falló antes de cualquier consulta; la causa más probable es que el
secreto `pps-prod-fortigate-token` conserva el valor de relleno que crea
Terraform [NV: no se leyó el secreto]. Los resultados válidos de esa corrida
son los de la ejecución local.

### 6.4 La aplicación

```powershell
.\.venv\Scripts\python.exe local-api\launch.py serve
```

Dejar esa consola abierta (la API escucha en `http://127.0.0.1:8765`). En otra
consola, desde la raíz:

```powershell
.\.venv\Scripts\python.exe gui\launch.py
```

En **Configuración → API local de desarrollo**, dejar `http://127.0.0.1:8765`
y pulsar **Conectar API local**. [I]

Qué se ve depende de lo que se haya traído de la PC original:

| Situación | Qué muestra la aplicación |
|---|---|
| Se copió `.pps-api\development.sqlite3` | Las dos corridas reales, con sus hallazgos y remediaciones |
| Se copió `audit-engine\local-runs\` y se tiene el PDF de la normativa | Nada hasta adjuntar cada reporte: [sección 8](#8-ver-resultados-en-la-aplicación) |
| No se copió nada | Una base vacía. Usar el modo de demostración con datos ficticios: `.\.venv\Scripts\python.exe gui\launch.py --demo` (la opción existe en el código [V]; la ventana no se abrió al escribir esta guía), o el botón **Abrir demostración** en **Configuración** |

La aplicación no muestra las referencias de la base de conocimientos de cada
control; están en el manifest y en el reporte (6.3).

### 6.5 Generar una corrida nueva (opcional, lo decide el usuario)

**Este paso escribe en AWS y consume tokens de Bedrock.** Un agente no lo
ejecuta sin un pedido explícito del usuario.

```powershell
aws s3 cp "<ruta>\<normativa>.pdf" "s3://$POLICIES/policies/<nombre>.pdf"
```

La subida dispara la Lambda generadora. En unos dos minutos aparecen
`manifest.json` y `script.py` bajo un `run_id` nuevo: [I]

```powershell
aws s3 ls "s3://$REPORTS/artifacts/"
aws logs tail "/aws/lambda/pps-prod-policy-generator" --since 10m
```

Como el generador está desplegado con `AUTO_EXECUTE=true` [V], la Lambda
ejecutora corre a continuación y, mientras no alcance un FortiGate, deja en
`reports/<run_id>/` un reporte sin datos como el de 6.3.

Con la cuota actual de Bedrock (10 pedidos por minuto [I]), varias generaciones
seguidas pueden recibir errores de límite; el cliente reintenta solo.

### 6.6 Versión completa, cuando exista el laboratorio en AWS

**Decisión de los dos autores (2026-11-22):** la demostración de la tesis se
hará con un **FortiGate de laboratorio dentro de AWS**, no con el equipo
institucional. Con un FortiGate alcanzable desde la Lambda ejecutora, todo el
flujo corre en AWS como lo describe la tesis: subir la normativa, esperar, y
ver en `reports/<run_id>/` un reporte con hallazgos reales, que la aplicación
trae con `aws sync`.

**El laboratorio todavía no está construido.** Es la próxima tarea. Lo que hay
y lo que falta está en la [sección 9](#9-estado-actual-defectos-conocidos-y-próximos-pasos).
Cuando exista, esta subsección debe reescribirse con los pasos reales.

## 7. Ejecución local a través de una VPN de usuario

Las dos ejecuciones reales se hicieron contra un FortiGate institucional que
solo es alcanzable por una VPN de usuario desde una estación Windows. Ese
camino sigue documentado y funciona, pero **ya no es el camino de la
demostración**.

| Script | Qué hace | Necesita |
|---|---|---|
| `audit-engine\scripts\run_executor_local.py <run_id>` | Lee el script y el manifest de S3, verifica el hash, vuelve a validar, comprueba la conectividad y ejecuta el sandbox en la estación. Escribe el reporte solo en `audit-engine\local-runs\` | `S3_BUCKET`, `FORTIGATE_HOST`, `FORTIGATE_TOKEN`, credenciales de AWS y la VPN |
| `audit-engine\scripts\diagnose_fortigate_local.py` | Informa la estructura de lo que devuelve cada endpoint (código HTTP, tipo, cantidades, nombres de campo), nunca los valores | `FORTIGATE_HOST`, `FORTIGATE_TOKEN` y la VPN. No usa AWS |

Ambos hacen solo lecturas `GET`, leen el token de la variable de entorno
`FORTIGATE_TOKEN` (nunca de un argumento) y no lo muestran. Procedimiento
completo, preparación del equipo, tratamiento del token y códigos de salida:
[local-executor-run.md](local-executor-run.md).

El ejecutor local corrió contra el equipo real [I]. El diagnóstico **no se
ejecutó nunca contra un equipo**: solo tiene tests con respuestas simuladas.

## 8. Ver resultados en la aplicación

Hay dos formas de que un reporte llegue a la aplicación:

| Origen del reporte | Cómo llega | Documento |
|---|---|---|
| Reporte en S3, escrito por la Lambda ejecutora | `local-api\launch.py aws sync` (necesita un archivo de configuración local) | [Manual de la API local](../../local-api/README.md) |
| Reporte local, escrito por `run_executor_local.py` | `local-api\launch.py import-result <aud_ID> <manifest.json> <report.json>` | [Sección 9 de la guía de ejecución local](local-executor-run.md#9-ver-el-reporte-local-en-la-aplicación-de-escritorio) |

Restricciones de `import-result`, que hay que conocer antes de intentarlo:

- La auditoría local debe haberse creado con **exactamente el mismo archivo**
  de normativa que usó el generador: se compara su SHA-256 con el del manifest.
- **No ejecutar `aws dispatch` antes de importar**: enviaría el documento a
  AWS, dispararía una generación nueva y la importación sería rechazada.
- Un resultado adjunto es inmutable. Para adjuntar otra corrida hay que crear
  otra auditoría.
- Después de importar, la base local contiene evidencia de la configuración
  real de un equipo, sin cifrar.

La sintaxis `import-result audit_id manifest report` se comprobó con `--help`
[V]; el procedimiento completo se ejecutó el 2026-11-21 [I].

## 9. Estado actual, defectos conocidos y próximos pasos

Estado detallado y con fechas: [status.md](status.md). Resumen:

### Qué funciona de punta a punta

| Tramo | Estado |
|---|---|
| Subir una normativa y obtener manifest y script validados, con referencias de la base de conocimientos | Funciona en AWS. Dos corridas reales [I] |
| Base de conocimientos: 24 documentos indexados, recuperación por consola y por CLI | Funciona [V] |
| Ejecución del script contra un FortiGate real, en modo de solo lectura | Funcionó dos veces por ejecución local sobre VPN [I]. **Nunca desde la Lambda** |
| Ver un reporte local en la aplicación | Funciona con `import-result` [I] |
| Tests, linters y evaluaciones offline | En verde [V] |

### Defectos conocidos

1. **Los scripts generados tratan un dato ausente como un valor.** En las dos
   corridas reales:
   - dos controles sobre administradores aprobaron con cero administradores
     leídos;
   - controles de registro y de FortiGuard mostraron valores por defecto para
     campos que el equipo no devolvió;
   - el control de NTP falla por no tener servidores propios aunque el equipo
     sincroniza con FortiGuard (criterio incorrecto, no dato ausente).

   La corrección está **diseñada y no implementada**:
   [decisión 12](decisions/12-datos-ausentes-indeterminate.md). Hasta que se
   implemente, un `pass` de esos controles no debe presentarse como evidencia
   de cumplimiento.
2. El diagnóstico de la forma de las respuestas existe pero no se ejecutó
   contra un equipo. Su salida es necesaria para cerrar las preguntas abiertas
   de la decisión 12.
3. La aplicación no muestra las referencias de la base de conocimientos.
4. Las evaluaciones de recuperación tienen `expected_sources` desactualizados
   respecto del corpus actual (`audit-engine/evals/retrieval/questions.json`).
5. Faltan dos fuentes del corpus que requieren descarga manual: el CIS
   FortiGate Benchmark y la guía CCN-STIC-1406
   ([manifiesto del corpus](rag/corpus.md)).
6. Una excepción en un script generado descarta todos los hallazgos de la
   corrida.

### Próximos pasos, en orden

**(a) Laboratorio FortiGate en AWS para la demostración.** No está hecho.

Lo que existe, comprobado leyendo el repositorio [V]:
`infrastructure/fortigate-lab` es un módulo de Terraform que crea una VPC
`10.0.0.0/16`, una subred pública, un grupo de seguridad con el puerto 443
abierto a `0.0.0.0/0`, un rol de solo lectura para el Fabric Connector y una
instancia FortiGate VM64 bajo demanda (`c5.large`, la AMI más reciente del
Marketplace). **Su región es `sa-east-1`; el pipeline está en `us-east-1`.**
No tiene variables, no fija la versión de FortiOS y no crea usuario de API ni
token. Si hoy está desplegado no se comprobó [NV].

Lo que hay que decidir y hacer, y quién:

| Tema | Qué decidir o hacer |
|---|---|
| Región | Llevar el laboratorio a `us-east-1`, o conectar las dos regiones. [La opción (b) del documento de conexión](../base/06-conexion-fortigate.md) recomienda la misma VPC y región que el pipeline |
| Alcance de red | La Lambda ejecutora hoy no está en una VPC [V]. Opciones: ponerla en una subred con ruta al puerto de gestión privado del FortiGate (variables `executor_subnet_ids` y `executor_security_group_ids`, más endpoints de VPC o NAT para S3, Secrets Manager y SNS), o exponer la gestión con una dirección pública restringida, que el documento de conexión no recomienda |
| Grupo de seguridad | Reemplazar `0.0.0.0/0` por el origen del executor |
| Host | Cargar la dirección del laboratorio en la variable de Terraform `fortigate_host`, que alimenta `FORTIGATE_HOST` |
| Token | Crear en el FortiGate el perfil de solo lectura y el usuario de API, y cargar el token en el secreto `pps-prod-fortigate-token` |
| Trusted hosts | Limitar el usuario de API a la subred del executor |
| Certificado | El laboratorio tendrá un certificado autofirmado: variable `fortigate_verify_ssl` |
| Versión de FortiOS | La base de conocimientos tiene documentación de FortiOS 7.6. La AMI «más reciente» puede ser otra versión: fijarla o registrar la diferencia |
| Licencia y costo | La instancia bajo demanda cobra por hora (instancia más licencia) y requiere aceptar la suscripción en el Marketplace. Apagarla o destruirla al terminar |
| Configuración de ejemplo | Un FortiGate recién creado tiene poca configuración: decidir qué políticas, perfiles y registros cargar para que la auditoría muestre algo |

Todo `terraform apply` lo ejecuta el usuario. Documentos de partida:
[conexión del FortiGate](../base/06-conexion-fortigate.md),
[README del laboratorio](../../infrastructure/fortigate-lab/README.md) y la
sección 8 del [paso a paso de despliegue](../base/02-paso-a-paso-despliegue-y-prueba.md).

**(b) Corrección de datos ausentes en el toolkit.** Ejecutar el diagnóstico
contra un equipo (el laboratorio sirve), cerrar las preguntas de la
[decisión 12](decisions/12-datos-ausentes-indeterminate.md) e implementarla.

**(c) El resto**, sin orden estricto: mostrar las referencias en la aplicación;
actualizar y grabar las evaluaciones de recuperación y de generación en vivo;
completar el corpus; aislar el fallo de un control del resto de la corrida;
medir con varias corridas por lado el efecto del corpus.

## 10. Solución de problemas

Problemas que ocurrieron en este proyecto. Las tres últimas filas son
previsibles en una PC nueva y no se observaron tal cual.

| Síntoma | Causa | Qué hacer |
|---|---|---|
| Un comando `aws` con JSON en línea falla en PowerShell con un error de formato | Windows PowerShell quita las comillas dobles del JSON | Usar la sintaxis abreviada: `--retrieval-query "text=..." --retrieval-configuration "managedSearchConfiguration={numberOfResults=3}"` |
| El ejecutor local responde 401 con un token correcto | El token se pegó en varias líneas o con caracteres de más | Copiarlo al portapapeles y cargarlo con `$env:FORTIGATE_TOKEN = (Get-Clipboard).Trim()`; comprobar el largo con `$env:FORTIGATE_TOKEN.Length`. Nunca imprimir el valor |
| El ejecutor local o el diagnóstico terminan con código 3 | El FortiGate no respondió la primera consulta | VPN desconectada; *trusted host* sin la dirección asignada por la VPN; puerto distinto de 443 (`host:puerto`); certificado autofirmado (`FORTIGATE_VERIFY_SSL=false`, solo en laboratorio); token regenerado. Tabla completa en [la guía](local-executor-run.md#8-si-falla-la-comprobación-de-conectividad) |
| La generación termina en `could_not_audit` con `bedrock_error`, o los registros muestran `ThrottlingException` | Cuota de Bedrock: 10 pedidos por minuto | Esperar y no lanzar varias generaciones seguidas. Antecedentes en [el resumen del RAG](rag/README.md) |
| Después de una ingesta, un documento borrado sigue apareciendo unos minutos | El índice lo muestra en `DELETE_IN_PROGRESS` hasta terminar | Esperar y volver a consultar; no relanzar la ingesta |
| `aws logs tail /aws/lambda/...` falla en Git Bash con una ruta de Windows | Git Bash convierte el argumento que empieza con `/` | Anteponer `MSYS_NO_PATHCONV=1` al comando, o usar PowerShell |
| `.git` dañado, o Terraform informa `missing or corrupted provider plugins` | El clon está dentro de Google Drive u otra carpeta sincronizada | Clonar fuera de carpetas sincronizadas; para Terraform, `TF_DATA_DIR` fuera del árbol ([TESTING.md](../../audit-engine/TESTING.md)) |
| Aparecen archivos `pps-reporte*.json` en la raíz | La aplicación propone ese nombre al exportar | Están ignorados por git en la raíz. No incorporarlos: contienen datos de reportes |
| Los tests del recuperador fallan con un error sobre `managedSearchConfiguration` | `boto3` quedó en la versión que fija `checkov` | Repetir el último comando de la sección 3.3 |
| La aplicación abre sin ventana | Quedó `QT_QPA_PLATFORM=offscreen` de los tests | `Remove-Item Env:QT_QPA_PLATFORM` |
| `python` o `py` no se reconocen | No están en el `PATH` | Usar siempre `.\.venv\Scripts\python.exe`; para crear el entorno, la ruta completa del intérprete |

## 11. Reglas para un agente

El contrato completo es [AGENTS.md](../../AGENTS.md). Lo que no admite
excepciones:

- **Solo lectura contra cualquier FortiGate.** Solo `GET` sobre el catálogo de
  endpoints. No agregar métodos de escritura ni código que aplique
  remediaciones.
- **No debilitar el validador ni el sandbox.** Si un script generado necesita
  algo que el validador rechaza, cambia el prompt o el catálogo.
- **Sin secretos en el repositorio**: ni credenciales de AWS, ni tokens, ni
  archivos `.env`, ni estados o variables de Terraform.
- **Sin valores de un equipo real en archivos con seguimiento**: ni en código,
  ni en tests, ni en documentación, ni en mensajes de commit. Los nombres de
  campo del esquema de FortiOS sí pueden usarse.
- **Terraform**: un agente puede ejecutar `fmt`, `init -backend=false` y
  `validate`. `plan` y `apply` los ejecuta el usuario.
- **AWS**: lecturas sí; cualquier escritura (subir una normativa, iniciar una
  ingesta, invocar una Lambda) solo por pedido explícito del usuario.
- **Git**: commits locales pequeños en la rama de la tarea, con Conventional
  Commits. `push`, `merge` y borrado de ramas requieren autorización explícita
  del usuario; tener los tests en verde no la reemplaza.
- **Tests primero** para cualquier cambio de comportamiento, y handoff
  actualizado en `docs/context/handoffs/`.

## Documentos relacionados

| Necesidad | Documento |
|---|---|
| Reglas, mapa de carpetas, contrato de entorno e IAM | [AGENTS.md](../../AGENTS.md) |
| Índice de contexto | [README.md](README.md) |
| Estado con fechas y fuentes | [status.md](status.md) |
| Ejecución local, diagnóstico y reporte en la aplicación | [local-executor-run.md](local-executor-run.md) |
| Base de conocimientos y corpus | [rag/README.md](rag/README.md), [rag/corpus.md](rag/corpus.md) |
| Diseño pendiente de datos ausentes | [decisions/12-datos-ausentes-indeterminate.md](decisions/12-datos-ausentes-indeterminate.md) |
| Conexión de un FortiGate | [06-conexion-fortigate.md](../base/06-conexion-fortigate.md) |
| Tests, Terraform y Checkov | [TESTING.md](../../audit-engine/TESTING.md) |
| API local y aplicación | [local-api/README.md](../../local-api/README.md), [gui/README.md](../../gui/README.md) |
| Informe académico | [informe/README.md](../../informe/README.md) |
