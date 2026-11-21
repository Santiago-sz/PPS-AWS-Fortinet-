# Evidencia del proyecto vinculada con el informe

Mantener una relación entre afirmaciones académicas y fuentes técnicas. Enlazar
los manuales canónicos; no duplicar procedimientos completos ni copiar secretos.

## Mapa inicial de consulta

| Tema del informe | Fuentes del proyecto | Uso y límite |
|---|---|---|
| Objetivo, alcance y restricciones | [Contrato](../../AGENTS.md), [proyecto](../../docs/context/project.md) | Auditoría de solo lectura y remediaciones propuestas |
| Arquitectura y componentes | [Arquitectura](../../docs/context/architecture.md), [mapa](../../docs/context/repository-layout.md) | Orientación; comprobar implementación concreta al redactar |
| Generación y ejecución | [Motor](../../audit-engine/), [verificación](../../audit-engine/TESTING.md), [evals](../../audit-engine/evals/README.md) | Diferenciar tests, fixtures offline y llamadas reales |
| API y escritorio | [Manual API](../../local-api/README.md), [manual GUI](../../gui/README.md) | Funciones documentadas; comprobar vigencia |
| Infraestructura | [Pipeline](../../infrastructure/pipeline/) | Terraform describe recursos; no demuestra despliegue actual |
| Pruebas locales y aceptación | [Handoff de validación](../../docs/context/handoffs/2026-11-15-local-functional-validation.md) | Pruebas registradas el 15/16 de noviembre de 2026 con resultados sintéticos |
| Decisiones y limitaciones | [Decisiones](../../docs/context/decisions/README.md), [estado histórico](../../docs/context/status.md) | Registrar fechas y contrastar información que pueda haber cambiado |

## Evidencia ya localizada

E-001: el handoff de validación funcional registra pruebas automatizadas GUI/API,
86 tests aprobados en la regresión conjunta y confirmación manual del usuario.
Se consultó el 2026-11-21 desde HEAD `5b50e8d`. Es evidencia histórica de flujo
local con datos sintéticos. No se repitieron pruebas ni se verificó AWS para
crear esta carpeta. La atribución al registro debe conservarse en la redacción.

Para cada afirmación nueva registrar: identificador, capítulo/sección, afirmación,
ruta o commit, fecha del hecho y de consulta, tipo de evidencia, límites y
propuesta que la utiliza. Separar implementación observada, ejecución verificada,
confirmación del usuario, hipótesis y trabajo pendiente. Una prueba sintética no
demuestra una auditoría de punta a punta con Bedrock y FortiGate reales.
