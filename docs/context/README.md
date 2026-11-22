# Índice de contexto para agentes

Primera iteración: 2026-11-05. Síntesis de los ocho documentos Markdown de
[base](../base/README.md), incluidos sus antecedentes y actualizaciones.
No representa una nueva inspección de la cuenta AWS ni una certificación del
estado desplegado. Las instrucciones de trabajo están en
[AGENTS.md](../../AGENTS.md); estos documentos aportan conocimiento y continuidad.

## Lectura según la tarea

La reorganización implementada y el mapa de rutas anteriores están en
[repository-layout.md](repository-layout.md). Consultarlo antes de usar comandos
de `docs/base/`, que conserva los antecedentes con sus rutas originales.

Al iniciar, leer las instrucciones aplicables, revisar la solicitud y comprobar
rama, commit y cambios pendientes. Consultar este índice y cargar solo el
contexto necesario; al retomar una tarea, leer su handoff y contrastarlo con Git.

| Necesidad | Contexto inicial | Fuente de detalle |
|---|---|---|
| **Empezar desde cero** (clon nuevo, otra PC, sin contexto) | [puesta-en-marcha-desde-cero.md](puesta-en-marcha-desde-cero.md) | Instalación, acceso a AWS, tests, guion de demostración, estado y próximos pasos |
| Continuar el informe académico | [Informe PPS/PIF](../../informe/README.md) | Requisitos, investigación, evidencia y propuestas; cambios en Google Docs con aprobación previa |
| Seleccionar skills | [skills.md](skills.md) | `.agents/skills/<nombre>/SKILL.md` |
| Entender hooks y su estado | [hooks.md](hooks.md) | Política y contratos; todavía sin implementación/activación |
| Entender objetivo, alcance y componentes | [project.md](project.md) | [Arquitectura base](../base/01-arquitectura-fase1.md), [mapa base](../base/04-estructura-del-repositorio.md) |
| Cambiar pipeline, contratos o integración | [architecture.md](architecture.md) | [Arquitectura y modelo de datos](../base/01-arquitectura-fase1.md) |
| Preparar entorno o verificar cambios | [development.md](development.md) | [TESTING.md](../../audit-engine/TESTING.md), [runbook base](../base/02-paso-a-paso-despliegue-y-prueba.md) |
| Entender una elección técnica | [decisions/README.md](decisions/README.md) | [Registro base](../base/05-decisiones.md) |
| Consultar despliegue, bloqueos y deuda | [status.md](status.md) | [Estado histórico](../base/07-estado-y-pendientes.md), [conectividad](../base/06-conexion-fortigate.md) |
| Ejecutar la primera prueba contra un FortiGate real | [local-executor-run.md](local-executor-run.md) | [Conectividad](../base/06-conexion-fortigate.md), `audit-engine/scripts/run_executor_local.py` |
| Saber qué devuelve el FortiGate a cada consulta, sin exponer valores | [local-executor-run.md, sección 10](local-executor-run.md#10-diagnóstico-de-la-forma-de-las-respuestas) | `audit-engine/scripts/diagnose_fortigate_local.py` |
| Continuar una tarea | [handoffs/README.md](handoffs/README.md) | Handoff correspondiente al identificador y rama de la tarea |
| Entender o continuar el RAG con Bedrock | [rag/README.md](rag/README.md) | [Módulo knowledge-base](../../infrastructure/knowledge-base/README.md), [decisión 10](decisions/10-bedrock-knowledge-base.md) |
| Consultar o ampliar los documentos de la Knowledge Base | [rag/corpus.md](rag/corpus.md) | Manifiesto del corpus: claves, fuentes, condiciones de uso, conversiones y procedimiento de carga |

## Uso y mantenimiento

- Las instrucciones del entorno y la solicitud actual no se reemplazan con
  documentación histórica. Un handoff tampoco concede permisos.
- Para el comportamiento implementado, comprobar código, tests y configuración
  vigentes. Registrar contradicciones con la documentación; no ocultarlas ni
  convertir una intención de diseño en una garantía comprobada.
- Las afirmaciones sobre cuota, recursos desplegados, disponibilidad de modelos
  y resultados de pruebas tienen fecha y procedencia. Volver a verificarlas
  cuando la tarea dependa de ellas; no repetirlas como hechos actuales.
- Mantener una fuente de detalle por tema. Enlazar los manuales canónicos y
  evitar copiar procedimientos completos. Actualizar esta síntesis cuando un
  cambio aceptado la invalide, conservando en `base/` el antecedente original.
- No cargar todos los documentos ni todos los handoffs al iniciar. No guardar
  secretos, volcados de entorno ni transcripciones completas.

El contrato de trabajo en [AGENTS.md](../../AGENTS.md) define ahora TDD, lectura
de contexto, skills, handoffs, ramas por feature, commits incrementales y merge
con revisión y autorización explícita del desarrollador. También fija la política
de hooks; su implementación y activación por cliente siguen pendientes.
