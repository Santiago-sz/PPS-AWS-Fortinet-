# Carpeta legacy — no editar

Esta carpeta es una copia obsoleta del código original de la Lambda de
assessment NIST (`handler.py`, `analyzer.py`, `reporter.py`,
`fortigate_client.py`, `secret_values.py`). El código canónico y mantenido
vive en `audit-pipeline/lambda/`, que incluye estas mismas funciones legacy
más el flujo policy-driven (`handler_generator.py`, `handler_executor.py`,
validador, sandbox, etc.) y su suite de tests. Ningún Terraform ni pipeline
empaqueta esta carpeta. Se conserva únicamente hasta que el dueño del
repositorio decida eliminarla; no aplicar cambios acá (ver `AGENTS.md`).
