# Limpieza de ramas al cerrar tareas

- Fecha: 2026-11-15. Tarea: branch-cleanup-policy.
- Objetivo autorizado: documentar y aplicar la eliminación de ramas de feature
  o fix terminadas, integradas y sin uso futuro.
- Rama: `feature/branch-cleanup-policy`, creada desde `master` en `32e0ac5`.
- Árbol inicial limpio. Cambios propios: AGENTS.md y este handoff e índice.
- Skills aplicadas: pps-review y pps-handoff, ya leídas en esta conversación.
- Regla: eliminación local segura; remota solo después de publicar la integración
  en origin/master; verificar ascendencia y consultar ante uso futuro incierto.
- La rama local `fix/functional-test-readiness` apunta a `32e0ac5`; la remota
  a `1eedd51`; ambos son antecesores de master y origin/master (`32e0ac5`).
- Limpieza autorizada de esa rama; no se incluyen otras ramas antiguas porque
  no se confirmó que ya no se utilizarán.
- Resultado: rama `fix/functional-test-readiness` eliminada localmente y en
  origin. El primer `branch -d` rechazó el borrado por upstream desactualizado;
  tras eliminar la rama remota, el segundo `branch -d` aprobó sin forzar.
- Verificación documental: diff y `git diff --check`; no corresponde TDD
  ejecutable ni repetir suites por una política documental.
- Revisión del desarrollador y merge de esta política pendientes. Publicar
  cambios documentales requiere autorización; el borrado remoto sí fue pedido.

## Autorización de integración

El 2026-11-15 el desarrollador indicó «integralo al master», autorizando el
merge de `feature/branch-cleanup-policy` (`d1298cb` más este registro) en
`master`. Integración mediante fast-forward y eliminación posterior de la
rama local conforme a la política. La rama de esta tarea no fue publicada.
El pedido no incluye push de master. Comprobaciones: árbol inicialmente
limpio y diff documental sin errores de espacios. No cambió código ejecutable.
