---
name: pps-audit-engine
description: "Cambiar el motor de auditoría PPS: generación Bedrock, contratos, ejecución, reportes o evals en audit-engine/. No usar para operar un FortiGate real ni aplicar remediaciones."
---

# Motor de auditoría PPS

Leer [AGENTS.md](../../../AGENTS.md),
[la arquitectura](../../../docs/context/architecture.md) y
[TESTING.md](../../../audit-engine/TESTING.md). Para generación o catálogo,
consultar además [evals](../../../audit-engine/evals/README.md).

- Ubicar la responsabilidad en `generator/`, `executor/`, `contracts/` o
  `legacy/`. Los imports de producción son planos porque Terraform reúne los
  módulos en la raíz del ZIP. Comprobar colisiones al agregar nombres.
- Escribir primero tests con respuestas Bedrock y datos FortiGate simulados.
  Para fallos de orquestación, comprobar reporte explícito y ausencia de ejecución
  posterior. Para presupuestos, comprobar estado parcial y evidencia preservada.
- Mantener separados generación y ejecución. El executor no importa el cliente
  del modelo y revalida hash y AST por cuenta propia antes del sandbox.
- Las restricciones del validador, sandbox, GET catalogados y código NIST legacy
  se rigen por el contrato. No ampliar allowlists para aceptar una salida del LLM;
  ajustar prompt o catálogo permitido y conservar el corpus adversarial.
- Si cambia prompt/modelo/catálogo, identificar fixtures y expectativas afectadas.
  Los evals offline no acreditan calidad live. La grabación live requiere alcance
  autorizado, disponibilidad y costo conocidos; si falta, declararla pendiente.

Ejecutar suite del motor, Ruff, formato y evals offline según el manual. Si cambia
el empaquetado o una variable de entorno, verificar también el contrato IaC/código
y la importación de handlers desde un paquete plano, sin plan/apply.
