---
name: pps-review
description: "Revisar un diff PPS o preparar commits y una entrega para revisión del desarrollador. Usar para control de cambios, evidencia y autorización de merge; no para conceder aprobación en nombre del desarrollador."
---

# Revisión y entrega PPS

Aplicar [el contrato Git y TDD](../../../AGENTS.md). Leer el diff de la tarea,
sus tests y el handoff; comparar contra la base acordada sin asumir una rama.

Para revisión, priorizar errores de comportamiento, regresiones, límites de
seguridad y contratos entre componentes. Citar ruta/línea, escenario e impacto.
Distinguir defectos comprobados de dudas o pruebas pendientes. Revisar especialmente
que no cambien las restricciones de AST/sandbox ni funciones NIST protegidas.

Para commits, comprobar rama de feature y pertenencia de los cambios. Revisar
índice y diff, seleccionar rutas/hunks explícitos y agrupar por incrementos
verificables; no incorporar cambios ajenos o artefactos. Si no es posible aislar
un incremento sin romper contratos, mantener juntos código, tests y documentación.
Usar los comandos de verificación del componente, sin repetir suites ya aprobadas
si no hubo cambios que invaliden su resultado.

La entrega incluye alcance, commits, evidencias, hallazgos y límites. No confundir
checks locales con CI remoto ni inferir éxito de despliegue. Una revisión del
agente no reemplaza la revisión del desarrollador requerida para merge.

Esperar autorización explícita para integrar el contenido revisado en el destino
indicado. Si cambia el diff, la autorización debe actualizarse. Push requiere
pedido propio; no inferirlo de la autorización de commits locales. No hacer merge,
force push, amend o rebase como efecto implícito de esta skill.
