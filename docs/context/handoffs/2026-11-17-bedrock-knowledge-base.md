# Base de RAG vectorial sobre una Knowledge Base administrada de Bedrock

- Fecha e identificador: 2026-11-17, bedrock-knowledge-base. Actualizado el
  2026-11-18 con un segundo incremento (sección «Incremento del 2026-11-18»,
  al final): **implementado y verificado en local, sin commit**.
- Estado: primer incremento registrado en commits; revisión del desarrollador
  y merge pendientes. **Ninguno de los dos incrementos hizo cambios en AWS.**
- Rama: `feature/bedrock-knowledge-base`; base `master` en `32e0ac5`.
- Commits: `16b45d3` (implementación) y un commit documental posterior con el
  [resumen de trabajo](../rag/README.md). Durante la implementación no se
  hicieron commits; el desarrollador pidió después (2026-11-17) registrar los
  cambios y publicar la rama en `origin`.
- Árbol inicial limpio; todos los cambios son de esta tarea.
- Merge: no autorizado.

## Objetivo y aceptación

Dejar todo lo necesario para que `policy_generator` PUEDA consultar una
Knowledge Base administrada de Bedrock, apagado por defecto y sin cambiar
ningún prompt ni comportamiento actual:

- Módulo Terraform aislado `infrastructure/knowledge-base/`.
- Cableado opcional en `infrastructure/pipeline/` (variables, entorno del
  generador, `bedrock:Retrieve` condicional y acotado).
- Módulo `audit-engine/generator/knowledge_retriever.py`, sin importar desde
  handlers ni `llm_client`.
- Documentación y contratos IaC/código actualizados en el mismo cambio.

Fuera de alcance: incorporar los fragmentos recuperados a los prompts de
`llm_client.py` (cambia prompts y exige regrabar fixtures en vivo).

## Restricciones y autorizaciones

- Sin `terraform plan`/`apply` ni comandos `aws`; solo `fmt`, `init
  -backend=false`, `validate` y `providers schema`.
- Sin commit, push, cambio de rama, stash, reset ni `git add`.
- Provider y lock de `infrastructure/pipeline/` intactos; `terraform.tfvars`
  y los estados locales del pipeline no se leyeron ni modificaron.
- Sin tocar `script_validator.py`, `sandbox.py`, legacy NIST, prompts de
  `llm_client.py` ni las carpetas legacy de raíz. Sin dependencias nuevas.

## Cambios propios

Nuevos:

- `infrastructure/knowledge-base/`: `main.tf`, `variables.tf`, `storage.tf`,
  `iam.tf`, `knowledge_base.tf`, `outputs.tf`, `.terraform.lock.hcl`,
  `README.md`.
- `audit-engine/generator/knowledge_retriever.py`.
- `audit-engine/tests/test_knowledge_retriever.py` (41 tests) y
  `audit-engine/tests/test_knowledge_base_iac.py` (24 tests).
- `docs/context/decisions/10-bedrock-knowledge-base.md` y este handoff.

Modificados:

- `infrastructure/pipeline/variables.tf` (`knowledge_base_id`,
  `knowledge_base_max_results`, ambas con validación), `lambda.tf` (dos
  variables de entorno en `policy_generator`), `iam.tf` (recurso nuevo
  `aws_iam_role_policy.generator_knowledge_base` con `count`),
  `terraform.tfvars.example`, `checkov-report.md`.
- `audit-engine/tests/test_repository_layout.py` (2 tests agregados; los
  existentes sin cambios), `audit-engine/TESTING.md`.
- `AGENTS.md` (mapa, contrato de entorno/IAM, comandos, conteo de tests),
  `docs/context/{architecture,repository-layout,status}.md`,
  `docs/context/decisions/README.md`, `docs/context/handoffs/README.md`,
  `.agents/skills/pps-terraform/SKILL.md` (menciona el módulo nuevo),
  `.github/workflows/ci.yml` (el job `terraform` valida también el módulo
  nuevo; comentario del conteo esperado de pytest).

## Decisiones y fuentes

Registro duradero: [decisión 10](../decisions/10-bedrock-knowledge-base.md).
Decisiones de implementación que conviene revisar:

1. **Permiso en una política aparte.** `bedrock:Retrieve` vive en
   `aws_iam_role_policy.generator_knowledge_base` (`count` según el id), no
   como statement condicional dentro de `generator_permissions`. Motivo: con
   el statement condicional (`concat` + condicional) Checkov dejó de evaluar
   la política principal (aprobados 109 -> 103); con la política aparte la
   principal queda byte-idéntica y Checkov evalúa ambas. El rol y el efecto
   son los pedidos: el permiso existe solo si el id no está vacío.
2. **Validación de `knowledge_base_id`**: vacío o hasta 10 caracteres
   alfanuméricos (patrón `KnowledgeBaseId` del modelo de servicio). Impide
   que un `*` o un ARN amplíen el recurso del permiso.
3. **Restricción del provider `~> 6.73`** en el módulo nuevo (no `~> 6.0`):
   6.73.0 es la versión con la que se validó el tipo `MANAGED`; no se
   determinó cuál es la primera 6.x que lo soporta.
4. **Consulta rechazada, no recortada**: vacía o de más de 20000 caracteres
   levanta `ValueError` sin llamar al servicio. Límite tomado de botocore
   1.43.123, `botocore/data/bedrock-agent-runtime/2023-07-26/service-2.json.gz`,
   shape `KnowledgeBaseQueryTextString` (`max: 20000`). `numberOfResults`:
   1..100 (shape `KnowledgeBaseVectorSearchConfigurationNumberOfResultsInteger`).
5. **Errores sin contenido**: `KnowledgeRetrievalError` lleva solo el código
   (`ClientError`) o el tipo (`BotoCoreError`, forma inesperada), y se levanta
   con `from None` para no encadenar el mensaje del servicio.
6. **Observabilidad**: un evento `kb_retrieve` por llamada
   (`knowledge_base_id`, `max_results`, `results`, `latency_ms`, `status`,
   `error` en fallos). Sin métricas EMF nuevas. Una entrada rechazada por
   validación no emite evento porque no hubo llamada.
7. Los resultados sin contenido textual se omiten; no se pagina (`nextToken`).

Fuentes: `AGENTS.md`, índice de contexto, `repository-layout.md`, código y
tests existentes, esquema del provider aws 6.73.0, documentación del provider
para los dos recursos de Bedrock y modelo de servicio de botocore.
Precios del README del módulo: dato del encargo con fecha 2026-11-17, no
verificado en esta tarea.

Skills: `pps-terraform`, `pps-audit-engine`, `pps-handoff` (leídas y
aplicadas como procedimiento).

## TDD y verificaciones

Tests escritos antes de implementar. Fallo inicial observado:

- Primera corrida: `ModuleNotFoundError: No module named 'knowledge_retriever'`
  al recolectar los dos archivos nuevos (solo evidencia de que faltaba el
  módulo).
- Con un esqueleto sin comportamiento: 54 fallidos por aserciones (39 de
  `test_knowledge_retriever.py` y 15 de `test_knowledge_base_iac.py`) y 15
  aprobados (tests de layout y guardas ya satisfechas, como el provider del
  pipeline intacto y la ausencia de Bedrock en el executor).
- Tras implementar el módulo Python: 41 aprobados en
  `test_knowledge_retriever.py`. Tras crear el módulo Terraform: quedaban 6
  fallidos, todos del cableado del pipeline; se agregó el test de validación
  del id (7 fallidos) y luego se implementó el cableado.
- El cambio de statement condicional a política aparte (decisión 1) obligó a
  reescribir dos tests propios de esta tarea; el requisito no cambió. Control
  negativo temporal, restaurado: sin `count` y con `knowledge-base/*` fallan
  3 tests.

Resultado final (2026-11-17, Windows, Python 3.12.10, pytest 8.3.5, Ruff
0.11.2, Terraform 1.15.9, Checkov 3.2.379), desde `audit-engine/`:

| Verificación | Resultado |
|---|---|
| `pytest -q -p no:cacheprovider` | 350 aprobados, 1 omitido (SIGALRM en Windows); antes 283 y 1 |
| `ruff check` / `ruff format --check` | Correctos |
| `evals/run_evals.py --mode offline` | Código 0, umbrales cumplidos, fixtures sin cambios |
| Pipeline: `fmt -check`, `init -backend=false`, `validate` | Correctos; provider aws 5.100.0 sin cambios |
| Knowledge Base: `fmt -check`, `init -backend=false`, `validate` | Correctos; provider aws 6.73.0 |
| Checkov pipeline | 118 aprobados, 29 fallidos (antes 109 y 29; mismos fallidos) |
| Checkov Knowledge Base | 19 aprobados, 4 fallidos (bucket: CKV_AWS_145, CKV_AWS_18, CKV_AWS_144, CKV2_AWS_62) |

Comprobación adicional fuera del repositorio: la expresión condicional de IAM
y la validación del id se evaluaron con `terraform console` en un directorio
temporal sin providers.

No verificado:

- Nada contra AWS: ni `plan`, ni creación de la base, ni `Retrieve` real.
- CI en Linux (se espera 351 aprobados sin omitidos; es una inferencia).
- Que `vectorSearchConfiguration` sea la configuración correcta para una
  base `MANAGED`: la API también ofrece `managedSearchConfiguration`.
- La estructura de `connector_parameters` y la suficiencia de los permisos
  del rol de servicio frente al servicio real.
- Que Lambda acepte `KNOWLEDGE_BASE_ID` con valor vacío en el entorno.
- `TESTING.md` conserva una nota anterior que atribuye al venv un botocore
  1.35.x; el venv actual tiene 1.43.123. No se corrigió en esta tarea.

## Pendientes, bloqueos y próximo paso

1. Incorporar los fragmentos recuperados al prompt de la fase reduce y
   registrarlos en el manifest; después, regrabar las fixtures de evals en
   vivo.
2. **Bloqueo**: cuota del modelo en Bedrock igual a 0 para Claude Sonnet 4.6
   en la cuenta; dos pedidos de aumento presentados el 2026-11-17, pendientes.
3. El corpus de documentos de la Knowledge Base todavía no está definido.
4. Despliegue del módulo nuevo por el operador (pasos en
   `infrastructure/knowledge-base/README.md`), con autorización explícita.
5. Confirmar que el boto3 incluido en el runtime python3.12 de Lambda expone
   `bedrock-agent-runtime.retrieve` en el entorno desplegado.

Próximo paso concreto: revisión del diff por el desarrollador; con su
aprobación, commits pequeños en esta rama y consulta de merge a `master`.

Los pendientes 1 y 2 de esta lista quedaron resueltos el 2026-11-18 (ver la
sección siguiente); la lista se conserva como registro del primer incremento.

## Incremento del 2026-11-18

- Base: `e86bbc1` en `feature/bedrock-knowledge-base`. Árbol inicial: un
  único cambio ajeno, `infrastructure/knowledge-base/knowledge_base.tf`,
  modificado por otro proceso que desplegaba ese módulo en paralelo. No se
  leyó, editó ni ejecutó nada en esa carpeta.
- Estado: implementado y verificado en local. **Sin commit, sin `git add`.**
  Revisión y merge pendientes; merge no autorizado.
- Restricciones del encargo: sin llamadas a AWS, sin `plan`/`apply`, sin
  tocar `infrastructure/knowledge-base/`, `script_validator.py`, `sandbox.py`,
  catálogo de endpoints ni funciones legacy; provider y lock del pipeline
  intactos; `terraform.tfvars` y estados sin leer.
- Skills: `pps-audit-engine`, `pps-terraform`, `pps-handoff` (leídas y
  aplicadas como procedimiento).

### Hechos informados en el encargo (no observados por el agente)

- El CI del commit `e86bbc1` aprobó sus cinco jobs en Linux
  ([run 44227778670](https://github.com/Santiago-sz/PPS-AWS-Fortinet-/actions/runs/44227778670)).
  La cantidad de tests aprobados en Linux no fue observada; el valor 351 de
  este handoff sigue siendo una inferencia.
- Los pedidos de cuota de Bedrock se cerraron. Cuota aplicada de Claude
  Sonnet 4.6, inferencia entre regiones: 6.000.000 tokens por minuto y 10
  pedidos por minuto (no los 10.000 pedidos). Una llamada mínima a Converse
  respondió correctamente. El bloqueo 2 de la lista anterior ya no rige.

### Objetivo y aceptación

1. Usar los fragmentos recuperados en la generación del script, con la base
   deshabilitada idéntica byte a byte a lo anterior.
2. Evaluación de calidad de recuperación en `audit-engine/evals/`.
3. Higiene documental (identificadores reales en `docs/base/`, afirmaciones
   desactualizadas y hechos del 2026-11-18).

### Cambios

Paquete 1, generación con referencia:

- Nuevos: `audit-engine/generator/reference_context.py`,
  `audit-engine/tests/test_reference_context.py`,
  `docs/context/decisions/11-referencias-en-generacion.md`.
- Modificados: `generator/knowledge_retriever.py` (filtro, constante de
  configuración de búsqueda, `fortios_version` en la configuración),
  `generator/llm_client.py` (`reference_provider`, `references`,
  `REFERENCE_SYSTEM_NOTE`), `generator/handler_generator.py`,
  `contracts/s3_io.py` (`knowledge_base` opcional en el manifest),
  `executor/toolkit.py` y `executor/reporter.py` (`references` por hallazgo);
  tests de esos módulos, `test_repository_layout.py` y
  `test_knowledge_base_iac.py`; `infrastructure/pipeline/variables.tf`,
  `lambda.tf` y `terraform.tfvars.example`
  (`knowledge_base_fortios_version` y `KNOWLEDGE_BASE_FORTIOS_VERSION`).

Paquete 2, evals de recuperación:

- Nuevos: `audit-engine/evals/retrieval_eval.py`,
  `evals/retrieval/questions.json`, `evals/retrieval/recorded.json`
  (sintética), `audit-engine/tests/test_retrieval_evals.py`.
- Modificados: `evals/run_evals.py` (`--suite`), `evals/thresholds.json`
  (clave `retrieval`), `evals/README.md`.

Paquete 3, higiene documental:

- `docs/base/*.md`: 39 reemplazos por marcadores neutros en 7 archivos.
- `lambda/README-LEGACY.md` y `terraform/README-LEGACY.md`: una línea cada
  uno, la ruta del código canónico. Es el único cambio en las carpetas
  legacy, indicado de forma explícita en el encargo.
- Comentario inicial de `handler_generator.py`, `docs/context/status.md`,
  `docs/context/handoffs/README.md`, `audit-engine/TESTING.md`,
  `.github/workflows/ci.yml` (comentario del conteo esperado).

Documentación común: `AGENTS.md`, `docs/context/architecture.md`,
`docs/context/rag/README.md`, decisiones 10 y 11 e índice, este handoff.

### Decisiones a revisar

Registro duradero: [decisión 11](../decisions/11-referencias-en-generacion.md).

1. **Manifest sin bloque = deshabilitado.** El encargo pide a la vez manifest
   idéntico con la base deshabilitada y que el manifest diga si la
   recuperación estuvo habilitada. Se resolvió así: el bloque
   `knowledge_base` solo existe cuando estuvo habilitada (`enabled: true`);
   su ausencia significa deshabilitada.
2. **Consulta**: `title` e `intent` del control. La estructura de un control
   no tiene un campo de valor esperado; la cita de `clause_ref` no se usa
   porque es texto de la normativa.
3. **Topes**: 40 llamadas, 3.000 caracteres por control y 80.000 en total,
   valores iniciales sin calibrar. Un fragmento de referencia nunca se
   recorta: entra entero o se omite. Con estos valores un fragmento de más
   de 3.000 caracteres queda siempre fuera.
4. **Configuración inválida con la base habilitada**: un
   `KNOWLEDGE_BASE_MAX_RESULTS` inválido hace fallar la invocación (igual que
   una variable requerida ausente). Con la base deshabilitada no se lee.
5. **Evento nuevo `kb_references`** con el resumen de la corrida, para que el
   resultado quede en los logs aun cuando la generación falla y no hay
   manifest.
6. **Origen = clave del objeto.** El servicio devuelve una URL cuyo bucket
   incluye el id de cuenta; `knowledge_retriever.source_identifier` conserva
   solo la clave antes de que llegue a prompt, manifest, reporte, eventos o
   fixtures. Hay tests con un URI de la cuenta ficticia `123456789012`.
7. **Validación de `knowledge_base_fortios_version`** en Terraform: vacío o
   versión numérica de hasta tres componentes.
8. **Evals de recuperación como suite del runner existente**
   (`--suite retrieval`), no como script aparte. `--suite` por defecto sigue
   siendo `generation`, de modo que el comando offline de siempre no cambia.
9. `local-api` y `gui` no se modificaron: leen manifest y reporte con `.get`
   y filtros por nombre de clave que no alcanzan a los campos nuevos. No se
   corrieron sus suites.

### TDD y verificaciones

Tests escritos antes de implementar.

- Primera corrida: `ModuleNotFoundError: No module named 'reference_context'`
  al recolectar `test_reference_context.py` (solo evidencia de que faltaba el
  módulo).
- Con un esqueleto sin comportamiento de `reference_context`: 61 fallidos y
  6 errores de fixture; 376 aprobados (los 350 previos y 26 guardas nuevas
  que ya se cumplían, entre ellas los hashes de prompts, manifest y reporte
  sin Knowledge Base). Fallos por comportamiento faltante: argumentos
  inexistentes (`metadata_filter`, `reference_provider`, `knowledge_base`),
  atributos inexistentes (`SEARCH_CONFIGURATION_KEY`, `equals_filter`,
  `retrieval_eval`), claves ausentes (`references`, bloque del manifest),
  variable de Terraform inexistente y aserciones de contenido.
- Tras implementar generador, manifest, toolkit y reporter: 8 fallidos y 6
  errores, todos del cableado Terraform y de las evals de recuperación. Tras
  el cableado y el runner: 4 fallidos por un error propio en la llamada a
  `score_question`; corregido, 443 aprobados.
- Segunda vuelta, con los hallazgos de la base real (ver más abajo): se
  actualizaron y agregaron tests primero; 24 fallidos (forma
  `managedSearchConfiguration`, `source_identifier` inexistente, origen como
  clave en manifest, prompt y evals, presupuesto por control) y 436
  aprobados. Tras implementar: 460 aprobados. Dos tests previos de
  `test_knowledge_retriever.py` que fijaban `vectorSearchConfiguration`
  cambiaron su expectativa porque el servicio demostró que era incorrecta.
- Los hashes de referencia se calcularon sobre `e86bbc1` antes de editar
  código de producción.

Resultado final (2026-11-18, Windows, Python 3.12, pytest 8.3.5, Ruff
0.11.2), desde `audit-engine/`:

| Verificación | Resultado |
|---|---|
| `pytest -q -p no:cacheprovider` | 460 aprobados, 1 omitido (SIGALRM en Windows); antes 350 y 1 |
| `ruff check` / `ruff format --check` | Correctos |
| `evals/run_evals.py --mode offline` | Código 0, umbrales cumplidos; `evals/recorded/`, `expected/` y `policies/` sin cambios |
| `evals/run_evals.py --suite retrieval --mode offline` | Código 0; 13 preguntas, acierto en 5 de 0,92 y MRR de 0,70 sobre fixture sintética |
| Pipeline: `fmt -check`, `init -backend=false`, `validate` | Correctos; provider y lock sin cambios |
| Checkov pipeline | 118 aprobados, 29 fallidos (igual que antes); `checkov-report.md` sin cambios |

Verificado contra el servicio el 2026-11-18, por fuera de este trabajo e
informado al agente (que no llamó a AWS):

- Una base `MANAGED` rechaza `vectorSearchConfiguration` con
  `ValidationException` y acepta
  `{"managedSearchConfiguration": {"numberOfResults": 3}}`. La constante
  `SEARCH_CONFIGURATION_KEY` quedó en `managedSearchConfiguration`.
- Cada resultado trae `score`, `content.text` y `location.s3Location.uri`
  como URL `https://<bucket>.s3.amazonaws.com/<clave>`.
- Pedir 3 resultados devolvió 2. Tamaños de fragmento para una consulta:
  9.943, 1.463, 1.109 y 1.082 caracteres.

No verificado:

- El código de este incremento contra AWS: ni `Retrieve` real, ni el modelo
  con la sección de referencia, ni `plan`.
- El filtro `fortios_version` dentro de `managedSearchConfiguration`: el
  modelo de servicio lo declara, ninguna consulta con filtro fue probada.
- El modo live de las evals de recuperación (solo con el recuperador
  simulado) y la calidad real de recuperación.
- El efecto de la referencia en los scripts generados; las fixtures grabadas
  no cubren ese camino.
- CI en Linux con este incremento (se espera 461 aprobados sin omitidos; es
  una inferencia).
- Suites de `local-api` y `gui`: no se ejecutaron porque no se modificaron.
- `infrastructure/knowledge-base/`: no se validó en este incremento.

### Pendientes y próximo paso

1. Revisión del diff por el desarrollador. Los tres paquetes están pensados
   para commits separados; `handler_generator.py`, `TESTING.md` y este
   handoff mezclan cambios de más de un paquete y requieren seleccionar
   hunks.
2. Fuera del alcance pedido y sin tocar: los diagramas `.drawio` de
   `docs/base/diagrams/` contienen el id de cuenta y el id de VPC (los `.png`
   pueden mostrarlos); `docs/base/*.md` conserva rutas locales del clon con
   el nombre de usuario de Windows; `audit-engine/evals/README.md` nombra el
   perfil local de AWS.
3. Con la base desplegada: probar una consulta con filtro, cargar
   documentos con el metadato `fortios_version`, ajustar
   `expected_sources` y grabar las evals de recuperación en vivo.
4. Regrabar las evals de generación en vivo con y sin la base.
5. Mostrar `references` en `gui` y `local-api`.

Próximo paso concreto: revisión del desarrollador; con su aprobación,
commits por paquete en esta rama y consulta de merge a `master`.

## Actualización 2026-11-18: despliegue y pruebas en vivo

- Autorización: el dueño del repositorio pidió de forma explícita desplegar
  en AWS, ejecutar las evaluaciones en vivo y una auditoría de punta a punta.
- Desplegados `infrastructure/knowledge-base` (9 recursos) y
  `infrastructure/pipeline` con la base habilitada; `plan` posterior de ambos
  sin cambios. Detalle y resultados en el [resumen de trabajo](../rag/README.md),
  sección «Estado al 2026-11-18».
- Commits de este tramo: `32d8069`, `25441e4`, `54f5955`, `4c9f95d`,
  `1a7bbfb`, `8bd93a5`, `d34f7d4`, `addaee8` y el commit documental que
  incluye esta actualización. Rama publicada en `origin`. Merge a `master`:
  pendiente de revisión y autorización.
- TDD en las correcciones: cada una partió de un test que reproducía la falla
  observada en vivo (JSON envuelto en bloque de código, respuesta de map
  cortada) y se observó su fallo antes de corregir. El cambio del prompt de
  generación se comprobó con las evaluaciones en vivo y el test que fija el
  hash del prompt se actualizó de forma deliberada.
- Verificaciones en Windows al cierre: `pytest` 464 aprobados y 1 omitido;
  `ruff check` y `ruff format --check` sin observaciones; evaluaciones
  offline con código de salida 0 sobre fixtures regrabadas en vivo.
- Decisión a revisar: la capa del generador ahora incluye boto3, lo que
  revierte la regla anterior de no incluirlo.
- Pendientes: ingesta nueva cuando termine el trabajo detenido; conectar un
  FortiGate real y cargar su token; confirmar la suscripción de correo;
  reemplazar la guía de Fortinet por la de la versión del equipo; regrabar la
  evaluación de recuperación contra el conjunto real; medir la variación en
  la cantidad de controles extraídos entre ejecuciones.

## Actualización 2026-11-21: corpus definitivo e ingesta completa

- Autorización: el dueño del repositorio autorizó de forma explícita, en la
  sesión, dos tipos de escritura en AWS: objetos en el bucket de conocimiento
  e inicio de ingestas en el origen de datos existente. Nada más se modificó:
  ni la Knowledge Base, ni el origen de datos, ni IAM, ni Lambdas, ni otros
  buckets; sin Terraform. No se disparó el generador ni se contactó ningún
  FortiGate.
- Base: `5cce6b4`. Árbol inicial limpio salvo `pps-reporte.json` en la raíz,
  ajeno a esta tarea y sin tocar.
- Skills: `amazon-bedrock` (referencias de Knowledge Base administrada).
- Hecho: causa de los dos fallos del trabajo `93LXHYAEHA` (el trabajo se
  detuvo antes de procesarlos); corpus de 25 documentos cargado en el bucket y
  reflejado en la copia local; ingesta `R4MQ9D7QQZ` en `COMPLETE` con 0
  fallidos y las tres normativas de ejemplo fuera del índice; recuperación
  comprobada con consultas de solo lectura, incluida la primera prueba del
  filtro por `fortios_version`. Resultados en el
  [resumen de trabajo](../rag/README.md); documentos, fuentes y conversiones
  en el [manifiesto del corpus](../rag/corpus.md).
- No se borró ningún objeto del bucket.
- Código: `audit-engine/scripts/stig_to_markdown.py` y sus tests (commit
  `e6250e6`). TDD: los 21 tests se escribieron primero y fallaron los 21
  contra un esqueleto sin comportamiento; tras implementar, 21 aprobados. Las
  demás conversiones (extracto del PDF de CLI, limpieza de las páginas de
  Infoleg, PDF de imágenes) se hicieron con scripts descartables fuera del
  repositorio; el manifiesto registra qué hizo cada una.
- Verificaciones (Windows): `pytest` 522 aprobados y 1 omitido; `ruff check`
  y `ruff format --check` sin observaciones. No se tocó Terraform ni código
  del generador o del executor, por lo que no se corrieron `validate`,
  Checkov ni las evaluaciones.
- Decisiones a revisar: metadatos `fortios_version` con la rama (`7.6`,
  `8.0`) y no la versión exacta; extracto de la referencia de CLI en lugar
  del documento completo; anexos de la Resolución AAIP 47/2018 cargados como
  PDF de imágenes sin transcribir; la guía de FortiOS 8.0.0 se conserva.
- Pendientes: retirar o no la guía de 8.0.0; ajustar `expected_sources` y
  grabar la evaluación de recuperación en vivo; regrabar las evals de
  generación con el corpus nuevo; decidir si se habilita el filtro en el
  pipeline; las dos fuentes que requieren un paso manual (CIS Benchmark y
  CCN-STIC-1406).
- Merge: no autorizado. Commits locales sin publicar.
