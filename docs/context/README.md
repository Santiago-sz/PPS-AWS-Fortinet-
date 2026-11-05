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
| Entender objetivo, alcance y componentes | [project.md](project.md) | [Arquitectura base](../base/01-arquitectura-fase1.md), [mapa base](../base/04-estructura-del-repositorio.md) |
| Cambiar pipeline, contratos o integración | [architecture.md](architecture.md) | [Arquitectura y modelo de datos](../base/01-arquitectura-fase1.md) |
| Preparar entorno o verificar cambios | [development.md](development.md) | [TESTING.md](../../audit-engine/TESTING.md), [runbook base](../base/02-paso-a-paso-despliegue-y-prueba.md) |
| Entender una elección técnica | [decisions/README.md](decisions/README.md) | [Registro base](../base/05-decisiones.md) |
| Consultar despliegue, bloqueos y deuda | [status.md](status.md) | [Estado histórico](../base/07-estado-y-pendientes.md), [conectividad](../base/06-conexion-fortigate.md) |
| Continuar una tarea | [handoffs/README.md](handoffs/README.md) | Handoff correspondiente al identificador y rama de la tarea |

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
