# Handoff: definición de skills y hooks

- Fecha: 2026-11-05, America/Buenos_Aires.
- Estado: definición completada y validada; implementación de hooks pendiente.
- Rama: `feature/project-skills-hooks`.
- Base de trabajo: `feature/fase1-harness-bedrock`, commit `d1b03f6`.
- Último commit antes de este incremento: `d1b03f6`; este handoff se incluye en
  el commit local de definición. No hay autorización de push ni merge para esta tarea.

## Objetivo y aceptación

Definir las skills y hooks del harness de desarrollo. Crear instrucciones
versionadas por responsabilidad, criterios de selección y contratos concretos
de hooks, sin modificar el producto ni activar automatizaciones no verificadas.

El árbol estaba limpio al comenzar. No se incorporaron cambios de otras tareas.
Se creó una rama propia desde el estado publicado de la conversación, sin
mezclar cambios de otras ramas ni elegir una rama de integración por su nombre.

## Resultado y decisiones

- Seis skills en `.agents/skills/`: `pps-gui`, `pps-local-api`, `pps-audit-engine`,
  `pps-terraform`, `pps-handoff` y `pps-review`.
- Catálogo y selección en [skills.md](../skills.md), enlazados desde `AGENTS.md`.
- Hooks definidos en [hooks.md](../hooks.md): carga de contexto, guarda de
  acciones sensibles, comprobación posterior a cambios, checkpoint, recuperación
  y cierre. Se especifican entradas/salidas, límites, fallos y aceptación futura.
- No hay handlers ni configuración ejecutable de hooks. La disponibilidad de
  eventos del cliente local no se comprobó; los mapeos de Codex son referencia.
- TDD y Git se mantienen como reglas comunes; las skills aportan procedimientos
  específicos y no conceden permisos. No se instala nada globalmente.
- Se corrigieron comandos obsoletos de Ruff y el nombre del paquete GUI en
  `docs/context/development.md` para que las referencias de las skills sean útiles.

Skills utilizadas: `skill-creator`, `openai-docs` y `pps-handoff` (lectura manual
de su archivo recién creado). No se presume actualización del catálogo dinámico
de la sesión. Fuente externa: documentación oficial de hooks de Codex, enlazada
en la definición; no se asumió compatibilidad con otros clientes.

## Verificación

Tarea de definición documental: no hay implementación ejecutable ni corresponde
crear tests artificiales. Se definieron como comprobaciones frontmatter, nombres,
enlaces y consistencia con `AGENTS.md` y las rutas del repositorio.

- Las seis skills pasan `quick_validate.py` de `skill-creator` con UTF-8 explícito.
- Setenta y cinco enlaces locales comprobados antes de agregar este handoff;
  comprobar también los enlaces añadidos al cerrar el incremento.
- `git diff --check` sin errores.
- No se ejecutaron suites del producto, Terraform, AWS ni hooks. El producto
  no cambió. No se realizaron instalaciones ni cambios de configuración global.
- El ejecutor restringido falló al preparar su entorno; se usó ejecución con
  elevación revisada para las lecturas y comprobaciones, sin modificar sus permisos.

## Próximo paso y revisión

Revisar estas definiciones con el desarrollador. Para implementar y activar
hooks, identificar cliente/versión, escribir primero los casos de aceptación
de `hooks.md`, implementar handlers y adaptadores y probarlos con ese cliente.
No presentar como activos los hooks aquí definidos. Revisar la configuración
exacta antes de confiarla y no eludir los mecanismos de confianza.

Merge pendiente de revisión y autorización explícita del desarrollador. Si cambia
el contenido revisado, debe obtenerse una aprobación actualizada. Push no incluido
en el alcance actual. Al retomar, comprobar Git y la solicitud vigente.
