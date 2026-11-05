# Skills del proyecto

Definición inicial: 2026-11-05. Skills versionadas en `.agents/skills/`, sin
instalaciones globales ni dependencias nuevas. Las reglas obligatorias de TDD,
Git y seguridad permanecen en [AGENTS.md](../../AGENTS.md).

## Catálogo y selección

| Skill | Cuándo usarla | Instrucciones |
|---|---|---|
| `pps-gui` | Vistas PySide6, interacción, dominio visual o cliente HTTP/HTTPS | [SKILL.md](../../.agents/skills/pps-gui/SKILL.md) |
| `pps-local-api` | Servidor local, cargas, SQLite, servicios o puente AWS explícito | [SKILL.md](../../.agents/skills/pps-local-api/SKILL.md) |
| `pps-audit-engine` | Generación Bedrock, ejecución, contratos, reportes y evals | [SKILL.md](../../.agents/skills/pps-audit-engine/SKILL.md) |
| `pps-terraform` | Recursos, IAM, red, configuración y empaquetado en infrastructure/ | [SKILL.md](../../.agents/skills/pps-terraform/SKILL.md) |
| `pps-handoff` | Retomar o preservar una tarea, preparar compactación y cerrar hitos | [SKILL.md](../../.agents/skills/pps-handoff/SKILL.md) |
| `pps-review` | Revisar un diff, agrupar commits o preparar una entrega revisable | [SKILL.md](../../.agents/skills/pps-review/SKILL.md) |

Elegir las skills que correspondan al alcance real. Para un cambio GUI que modifica
el contrato HTTP, usar GUI y API; para un cambio de variable Lambda, motor y
Terraform. Un ajuste de texto no obliga a cargar todas las skills del componente.

Leer primero nombre/descripción, después el `SKILL.md` elegido y solo sus fuentes
pertinentes. Anunciar su uso y registrarlo en el handoff. Las rutas enlazadas son
relativas al archivo que las contiene; los comandos se ejecutan desde los
directorios que indica cada manual, con el Python del entorno disponible.

Los clientes con descubrimiento compatible pueden incorporar este catálogo al
abrir el proyecto. Si no aparece automáticamente, leer los archivos directamente
siguiendo `AGENTS.md` y declarar el uso manual. No afirmar que el catálogo dinámico
del cliente se actualizó durante una sesión sin comprobarlo.

## Skills del entorno y externas

El catálogo proporcionado por el entorno del agente puede complementar estas
skills. No se copia al repositorio una ruta personal ni se presume que está
instalado en otra máquina. En este trabajo se utilizaron `skill-creator` para
redactar y validar las skills y `openai-docs` para consultar el diseño de hooks.
No constituyen dependencias obligatorias de producción de este repositorio.

No se instalan skills o plugins por activación implícita. Si falta una capacidad,
seguir el procedimiento equivalente cuando sea viable e informar la limitación.
Ninguna skill concede autorización de push, merge, AWS o despliegue.

## Mantenimiento y verificación

Cada skill tiene frontmatter YAML con `name` y `description`, nombre coincidente
con la carpeta, límites de activación y referencias existentes. No contiene
scripts ejecutables ni placeholders en esta primera versión.

Antes de cambiarla, definir casos de uso y comprobar que se selecciona para las
tareas correctas, sin absorber tareas ajenas. Para cambios documentales, validar
frontmatter, enlaces y consistencia con el contrato. Si se agregan scripts,
escribir primero pruebas de su comportamiento, observar el fallo inicial y
ejecutarlos en recursos de prueba antes de utilizarlos en tareas reales.
