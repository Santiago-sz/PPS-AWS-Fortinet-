# Knowledge Base administrada de Amazon Bedrock

Módulo Terraform aislado que crea la base para un RAG vectorial del
generador de auditorías: un bucket S3 de documentos, un rol de servicio, una
Knowledge Base administrada (`MANAGED`) y su data source S3.

Estado al 2026-11-17: **implementado y validado localmente; no desplegado**.
Ningún comando de este documento fue ejecutado contra AWS. El pipeline no
consulta la Knowledge Base todavía: `policy_generator` recibe la
configuración y el permiso solo cuando el operador lo habilita, y los
fragmentos recuperados aún no se incorporan a ningún prompt.

## Qué crea

| Recurso | Nombre | Notas |
|---|---|---|
| `aws_s3_bucket.knowledge` | `<prefijo>-knowledge-<account_id>` | Versionado, bloqueo total de acceso público, SSE-S3 y ciclo de vida, igual que los buckets del pipeline |
| `aws_iam_role.knowledge_base` | `<prefijo>-knowledge-base-role` | Solo lo asume `bedrock.amazonaws.com`, con condiciones `aws:SourceAccount` y `aws:SourceArn` (Knowledge Bases de la misma cuenta y región) |
| `aws_iam_role_policy.knowledge_base` | `<prefijo>-knowledge-base-policy` | `s3:ListBucket` sobre el bucket y `s3:GetObject` sobre sus objetos; sin comodines en `Resource` |
| `aws_bedrockagent_knowledge_base.this` | `<prefijo>-knowledge-base` | Tipo `MANAGED`, embeddings `MANAGED`, sin `storage_configuration` |
| `aws_bedrockagent_data_source.documents` | `<prefijo>-knowledge-documents` | Conector `MANAGED_KNOWLEDGE_BASE_CONNECTOR` de tipo S3 sobre el bucket del módulo |

`<prefijo>` es `${project_name}-${environment}` (por defecto `pps-prod`), el
mismo que usa `infrastructure/pipeline/`.

Outputs: `knowledge_base_id`, `knowledge_base_arn`, `data_source_id` y
`knowledge_bucket`.

## Por qué está separado del pipeline

Las Knowledge Bases administradas requieren el provider `hashicorp/aws` 6.x.
El pipeline desplegado está fijado en 5.100.0 (`~> 5.0`) y subir su provider
obligaría a revisar todos sus recursos ya desplegados. Este módulo tiene su
propia restricción (`~> 6.73`; validado con 6.73.0), su propio
`.terraform.lock.hcl` versionado y su propio estado. El único vínculo con el
pipeline es el id de la Knowledge Base, que se pasa a mano como variable.

No mezclar los estados de ambos módulos ni ejecutar uno desde el directorio
del otro.

## Costos

Modelo publicado por AWS en la página de precios de Amazon Bedrock,
consultado el 2026-11-17 por el responsable del proyecto (este módulo no lo
verifica; confirmarlo en la página oficial antes de desplegar):

| Concepto | Precio |
|---|---|
| Almacenamiento del índice | USD 5 por GB de datos sin procesar por mes |
| Consultas `Retrieve` | USD 1 por cada 1.000 llamadas |
| Parsing, embeddings y reranking administrados | USD 0 |
| Mínimo mensual | No se indica ninguno |

Además se paga el almacenamiento S3 normal de los documentos. Con un corpus
pequeño (decenas de MB) el costo esperado es de centavos por mes, pero
depende del volumen real y de la cantidad de consultas.

## Despliegue e ingesta (pasos para el operador, no ejecutados)

Requieren credenciales AWS con permisos de administración sobre S3, IAM y
Bedrock, y la autorización explícita del responsable del repositorio
(`AGENTS.md`, regla 10). Conviene mantener `TF_DATA_DIR` fuera del árbol del
repositorio, como en el pipeline.

```bash
export TF_DATA_DIR="C:/Users/<usuario>/.terraform-data/pps-knowledge-base"
cd infrastructure/knowledge-base

# 1. Inicializar, revisar el plan y aplicar
terraform init
terraform plan -out tfplan
terraform apply tfplan

# 2. Anotar los outputs
terraform output knowledge_base_id
terraform output data_source_id
terraform output knowledge_bucket

# 3. Subir los documentos del corpus al bucket
aws s3 cp ./documentos/ "s3://<knowledge_bucket>/" --recursive

# 4. Iniciar la ingesta (no es automática)
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id <knowledge_base_id> \
  --data-source-id <data_source_id> \
  --region us-east-1

# 5. Esperar a que el trabajo termine con estado COMPLETE
aws bedrock-agent get-ingestion-job \
  --knowledge-base-id <knowledge_base_id> \
  --data-source-id <data_source_id> \
  --ingestion-job-id <ingestion_job_id> \
  --region us-east-1 \
  --query "ingestionJob.status"

# 6. Verificar la recuperación
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id <knowledge_base_id> \
  --retrieval-query '{"text": "requisitos de acceso administrativo"}' \
  --retrieval-configuration '{"vectorSearchConfiguration": {"numberOfResults": 3}}' \
  --region us-east-1
```

Cada vez que cambien los documentos del bucket hay que repetir los pasos 4
a 6. El plan generado (`tfplan`) no se versiona.

## Conexión con el pipeline

Con la Knowledge Base creada y la ingesta en `COMPLETE`, pasar su id al
módulo `infrastructure/pipeline/` en `terraform.tfvars`:

```hcl
knowledge_base_id          = "<knowledge_base_id>"
knowledge_base_max_results = 5
```

Al aplicar el pipeline con ese valor:

- `policy_generator` recibe `KNOWLEDGE_BASE_ID` y
  `KNOWLEDGE_BASE_MAX_RESULTS`.
- Se crea la política `aws_iam_role_policy.generator_knowledge_base` con
  `bedrock:Retrieve` sobre el ARN exacto de esa base.

Con `knowledge_base_id = ""` (valor por defecto) esa política no existe y
`knowledge_retriever.load_config()` informa la recuperación deshabilitada.
`audit_executor` y el assessor legacy nunca reciben permisos sobre la base.

## Verificación local

Desde `audit-engine/`, sin credenciales AWS:

```bash
TF_DATA_DIR=C:/Users/<usuario>/.terraform-data/pps-knowledge-base terraform -chdir=../infrastructure/knowledge-base fmt -check -recursive
TF_DATA_DIR=... terraform -chdir=../infrastructure/knowledge-base init -backend=false -input=false
TF_DATA_DIR=... terraform -chdir=../infrastructure/knowledge-base validate
PYTHONUTF8=1 ../.venv/Scripts/python.exe -m checkov.main -d ../infrastructure/knowledge-base --framework terraform --compact
```

Los contratos del módulo (tipo `MANAGED`, conector, condiciones de
confianza, ausencia de comodines, endurecimiento del bucket) se comprueban
en `audit-engine/tests/test_knowledge_base_iac.py`.

### Resultado de Checkov (2026-11-17, Checkov 3.2.379)

**19 aprobados, 4 fallidos, 0 omitidos**, sin errores de parseo. Los cuatro
fallidos son del bucket `aws_s3_bucket.knowledge` y corresponden a los
mismos hallazgos aceptados para los buckets del pipeline (ver
[checkov-report.md](../pipeline/checkov-report.md)):

| Check | Motivo |
|---|---|
| CKV_AWS_145 (cifrado con KMS) | Usa SSE-S3; una clave propia es una decisión de costo y gobierno fuera de alcance |
| CKV_AWS_18 (access logging) | Diferido, igual que en el pipeline |
| CKV_AWS_144 (replicación entre regiones) | Diferido, igual que en el pipeline |
| CKV2_AWS_62 (notificaciones de eventos) | No hay un consumidor de eventos; la ingesta la inicia el operador |

Esta versión de Checkov no informó checks específicos sobre los recursos
`aws_bedrockagent_*`. Una validación estática aprobada no demuestra un
despliegue correcto.

## Limitaciones conocidas

- `terraform validate` comprueba el esquema del provider, no la aceptación
  del servicio. La estructura de `connector_parameters` proviene del ejemplo
  de la documentación del provider y no fue probada contra AWS.
- No se verificó si el rol de servicio necesita permisos adicionales a la
  lectura del bucket para una Knowledge Base administrada.
- La API `Retrieve` ofrece `vectorSearchConfiguration` y también
  `managedSearchConfiguration`. `knowledge_retriever.py` usa la primera; falta
  confirmar con una base real cuál corresponde al tipo `MANAGED`.
- El corpus de documentos todavía no está definido.
