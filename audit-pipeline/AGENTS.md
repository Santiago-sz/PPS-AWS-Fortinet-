# Pipeline de auditoria

- Leer `TESTING.md` para contexto historico; los comandos consolidados actuales
  estan en `../docs/HARNESS.md`.
- `lambda/handler.py` es el assessor NIST anterior; `handler_generator.py` y
  `handler_executor.py` implementan el flujo de politicas. Conservar esa distincion.
- Mantener las importaciones planas de Lambda y ejecutar pytest/Ruff desde
  `audit-pipeline/`; el runner ya elige ese directorio.
- Los agentes de etapa se registran en `lambda/audit_agents.py`; sus instrucciones
  viven en `lambda/agent_prompts.py`. Ver `../docs/AGENTS_RUNTIME.md` y revisar la
  version del agente al cambiar instrucciones. No confundirlos con AGENTS.md.
- Conservar validacion AST, SHA-256 y revalidacion independiente del ejecutor.
  Los limites y reintentos deben ser acotados; nunca convertir resultados
  `truncated` o `could_not_audit` en auditorias completas.
- Usar mocks de AWS/FortiGate/modelo. Ejecutar el perfil `pipeline`; si cambia el
  empaquetado, IAM o variables de entorno ejecutar tambien `iac`.
- No confundir las comprobaciones estaticas de IaC con una prueba de despliegue
  ni con una garantia de aislamiento del codigo generado.
