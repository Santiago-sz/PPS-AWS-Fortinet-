# Base de RAG vectorial sobre una Knowledge Base administrada de Bedrock

- Fecha e identificador: 2026-11-17, bedrock-knowledge-base.
- Estado: implementado localmente, **sin commits**; revisión del desarrollador
  y merge pendientes. **No se hizo ningún cambio en AWS.**
- Rama: `feature/bedrock-knowledge-base`; base `master` en `32e0ac5`, que es
  también el último commit (HEAD) al cerrar este incremento.
- Árbol inicial limpio; todos los cambios pendientes son de esta tarea.
- Merge: no autorizado. Commits: no realizados por indicación del encargo
  (los cambios quedan en el árbol de trabajo para revisión).

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
