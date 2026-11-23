# Continuidad de tareas

Un handoff resume el estado verificable de una tarea para retomarla tras
compactación o cambio de sesión. No reemplaza las instrucciones actuales ni
autoriza acciones nuevas. Leer solo el que corresponda a la tarea y contrastarlo
con la rama, el commit y los cambios pendientes de Git.

| Tarea | Estado |
|---|---|
| [2026-11-22-gui-driven-lab-audits](2026-11-22-gui-driven-lab-audits.md) | Auditorías del laboratorio desde la aplicación de escritorio: red privada del executor con emparejamiento de VPC (`infrastructure/executor-network`), ciclo opcional de envío en la API local e inicio de la API desde la aplicación. Validado en forma estática y con tests; sin aplicar en AWS ni probar de punta a punta. Revisión y merge pendientes |
| [2026-11-22-fortigate-lab-aws](2026-11-22-fortigate-lab-aws.md) | Laboratorio FortiGate desechable en AWS (`infrastructure/fortigate-lab`): Terraform reescrito, validado en forma estática y documentado. Aplicado en AWS el 2026-11-22; revisión y merge pendientes |
| [2026-11-22-toolkit-absent-data](2026-11-22-toolkit-absent-data.md) | Decisión 12 implementada en `fix/toolkit-absent-data`: el toolkit guarda `indeterminate` ante datos ausentes y se corrigieron dos rutas del catálogo. Verificado solo con tests; corrida contra un equipo, revisión y merge pendientes |
| [2026-11-22-puesta-en-marcha-desde-cero](2026-11-22-puesta-en-marcha-desde-cero.md) | Guía de entrada para empezar desde cero en otra PC y propuesta de diseño de datos ausentes (decisión 12): escritas y comprobadas. Revisión de los autores pendiente |
| [2026-11-22-fortigate-shape-diagnostic](2026-11-22-fortigate-shape-diagnostic.md) | Diagnóstico de solo lectura de la forma de las respuestas del FortiGate: implementado con tests y documentado. Ejecución contra el equipo, revisión y merge pendientes |
| [2026-11-21-local-executor-runner](2026-11-21-local-executor-runner.md) | Ejecución local del executor para la primera prueba por VPN de usuario: implementada con tests y documentada. Prueba real, revisión y merge pendientes |
| [2026-11-21-informe-academico](2026-11-21-informe-academico.md) | Estructura y contexto inicial en `/informe`; revisión del autor pendiente |
| [2026-11-17-bedrock-knowledge-base](2026-11-17-bedrock-knowledge-base.md) | Base de RAG en commits `16b45d3` y `e86bbc1` (CI de `e86bbc1` aprobado). Incremento del 2026-11-18 sin commit: fragmentos recuperados en la fase reduce, trazabilidad en manifest y reporte, filtro por versión y evals de recuperación. Deshabilitada por defecto; revisión y merge pendientes. Actualización del 2026-11-21: corpus definitivo de 25 documentos cargado e ingerido sin fallos, con su manifiesto y un conversor de STIG a Markdown |
| [2026-11-15-local-functional-validation](2026-11-15-local-functional-validation.md) | Smoke GUI/API real local aprobado; revisión manual y E2E pendientes |
| [2026-11-15-functional-test-readiness](2026-11-15-functional-test-readiness.md) | Tres correcciones verificadas, CI en Linux aprobado el 2026-11-15 e integradas en `master` |
| [2026-11-15-branch-cleanup-policy](2026-11-15-branch-cleanup-policy.md) | Regla de limpieza de ramas; merge pendiente |
| [2026-11-05-skills-hooks](2026-11-05-skills-hooks.md) | Seis skills validadas y hooks definidos; implementación/activación pendiente |
| [2026-11-05-reorganizacion-repositorio](2026-11-05-reorganizacion-repositorio.md) | Arquitectura implementada, integrada en `master` y con CI remoto aprobado (2026-11-15) |
| [2026-11-05-contexto-inicial](2026-11-05-contexto-inicial.md) | Primera iteración documental; definición de AGENTS, skills y hooks pendiente |

## Convención

Un archivo `<id-tarea>.md` por tarea; actualizarlo al alcanzar hitos importantes,
antes de compactar cuando haya aviso y al dejar trabajo inconcluso. No esperar
a llenar la ventana: el aviso no está garantizado. Evitar sobrescribir el estado
de otra tarea o elegir un handoff únicamente porque es el más reciente.

Contenido mínimo:

1. Identificador, fecha, estado, rama y commit de referencia.
2. Objetivo, aceptación y restricciones del usuario.
3. Cambios preexistentes y cambios propios, separados.
4. Decisiones, fuentes consultadas y skills utilizadas.
5. Estado TDD: tests escritos, fallo inicial, implementación y resultado; para
   documentación, las comprobaciones pertinentes.
6. Verificaciones realmente ejecutadas, pendientes y limitaciones.
7. Bloqueos, dudas y próximo paso concreto.

Guardar hechos y decisiones útiles; no secretos, transcripciones completas ni
razonamiento interno. Al completar una tarea, marcar su estado y trasladar el
conocimiento duradero al contexto o al registro de decisiones correspondiente.
