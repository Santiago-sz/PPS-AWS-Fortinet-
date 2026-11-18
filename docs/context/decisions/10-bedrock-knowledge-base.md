# 10 — Knowledge Base administrada de Bedrock como base de RAG

- Fecha: 2026-11-17.
- Estado: aceptada en el encargo de la tarea `bedrock-knowledge-base`;
  implementación local pendiente de revisión del desarrollador y de merge.
- No sustituye ninguna decisión anterior. Complementa ADR-01 (modelo por
  Bedrock e IAM) y ADR-05 (executor sin modelo).

## Problema

Se quiere que el generador pueda apoyarse en documentos de referencia
(recuperación vectorial) sin alterar el comportamiento actual, sin regrabar
fixtures de evals mientras la cuota del modelo en la cuenta es 0, y sin poner
en riesgo el pipeline ya desplegado.

## Opciones consideradas

| Opción | Resultado |
|---|---|
| Agregar la Knowledge Base al módulo `infrastructure/pipeline/` | Descartada: las Knowledge Bases administradas requieren el provider aws 6.x y el pipeline desplegado está fijado en 5.100.0 (`~> 5.0`); subirlo obliga a revisar todos sus recursos |
| Knowledge Base con almacén vectorial propio (OpenSearch Serverless u otro) | Descartada: más recursos, más permisos y un costo fijo que no se justifica para el corpus previsto |
| Reemplazar el map/reduce por recuperación de fragmentos | Descartada: se pierde la cobertura completa de la normativa y la trazabilidad por cláusula |
| Módulo aislado con Knowledge Base administrada, recuperación aditiva y apagada por defecto | **Elegida** |

## Decisión

1. **Módulo Terraform separado** `infrastructure/knowledge-base/`, con su
   propia restricción de provider (`~> 6.73`), su lock versionado y su propio
   estado. El provider y el lock del pipeline no se modifican.
2. **Knowledge Base administrada** (`MANAGED`, embeddings `MANAGED`, conector
   S3 administrado): sin almacén vectorial propio.
3. **La recuperación es aditiva.** Los fragmentos recuperados aportan contexto
   de apoyo; nunca reemplazan el map/reduce completo sobre la normativa, que
   es lo que mantiene la cita de cláusula en cada control y hallazgo. La regla
   7 de `AGENTS.md` (no truncar la normativa) sigue vigente sin cambios.
4. **Deshabilitada por defecto.** `knowledge_base_id = ""` en el pipeline:
   sin id no hay permiso `bedrock:Retrieve` ni consulta. El permiso, cuando
   existe, es una política aparte del rol del generador sobre el ARN exacto
   de la base. El executor y el assessor legacy no reciben permisos nuevos.
5. **Este incremento no cambia prompts.** `knowledge_retriever.py` no lo
   importa ningún handler ni `llm_client`. Incorporar fragmentos al prompt de
   reduce y registrarlos en el manifest es un cambio posterior, que exige
   regrabar las fixtures de evals en vivo.

## Consecuencias

- Dos módulos Terraform con versiones distintas del provider: no compartir
  `TF_DATA_DIR` ni estados. El id de la base se pasa a mano entre ambos.
- El ZIP común de las Lambdas incluye `knowledge_retriever.py` también en el
  executor y el assessor (empaquetado preexistente). La separación la dan los
  permisos IAM y la ausencia de imports, verificadas por tests.
- Aplicar el pipeline tras este cambio actualiza en sitio el código y el
  entorno de las Lambdas (dos variables nuevas en el generador); no reemplaza
  recursos. No fue comprobado con `terraform plan`.
- Costos de la base administrada: ver el README del módulo (precios con
  fecha 2026-11-17, a confirmar antes de desplegar).

## Fuentes

- Esquema del provider `hashicorp/aws` 6.73.0 (`terraform providers schema
  -json`) y documentación del provider para `aws_bedrockagent_knowledge_base`
  y `aws_bedrockagent_data_source`.
- Modelo de servicio de botocore 1.43.123, `bedrock-agent-runtime`
  (operación `Retrieve`).
- [Handoff de la tarea](../handoffs/2026-11-17-bedrock-knowledge-base.md) y
  [README del módulo](../../../infrastructure/knowledge-base/README.md).
