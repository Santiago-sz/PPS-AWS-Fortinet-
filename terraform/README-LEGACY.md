# Carpeta legacy — no editar

Esta carpeta es una copia obsoleta del Terraform original del pipeline
(una sola Lambda de assessment NIST). La infraestructura canónica y
mantenida vive en `audit-pipeline/terraform/` (tres Lambdas, buckets de
políticas y reportes, roles de mínimo privilegio, DLQ, alarmas, logging de
Bedrock). No hay estado remoto asociado a esta copia y ningún flujo de CI la
valida. Se conserva únicamente hasta que el dueño del repositorio decida
eliminarla; no aplicar cambios ni ejecutar `terraform` acá (ver `AGENTS.md`).
