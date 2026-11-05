# Definición de hooks de desarrollo

Fecha: 2026-11-05. Estado: **definidos; no implementados ni activados**.
Este documento especifica responsabilidades, contratos y pruebas para una
implementación posterior. No existe todavía una configuración ejecutable del
proyecto en `.codex/hooks.json`, ni se modificó configuración global del cliente.
Aplicar por ahora las comprobaciones manuales de [AGENTS.md](../../AGENTS.md).

## Catálogo

Los identificadores propios del proyecto son estables. La columna de eventos
Codex es un mapeo de referencia, no evidencia de soporte en el cliente instalado.

| ID | Momento / evento Codex de referencia | Comprobación | Resultado esperado |
|---|---|---|---|
| `context-load` | Inicio o reanudación / `SessionStart` | Raíz del repo, rama/HEAD/estado e instrucciones/índice disponibles; handoff de la tarea cuando esté identificado | Contexto breve con rutas y discrepancias; no cargar documentos completos |
| `action-guard` | Antes de herramienta / `PreToolUse` | Acción y destinos normalizados contra rutas protegidas, alcance y autorizaciones verificables | Permitir o bloquear la acción con motivo concreto |
| `change-check` | Tras edición relevante / `PostToolUse` | Componentes afectados y verificaciones previas que el nuevo cambio invalida | Lista de comprobaciones pendientes; no ejecutar toda la suite |
| `context-checkpoint` | Antes de compactar / `PreCompact` | Handoff de tarea existente y consistente con rama/HEAD/cambios; estado mecánico recuperable | Advertir ausencias y preservar metadatos mínimos por sesión |
| `context-resume` | Tras compactar / `SessionStart` con origen de compactación | Coincidencia del checkpoint con la sesión/tarea y estado Git actual | Recordatorio de lectura y discrepancias; no continuar ciegamente |
| `delivery-check` | Cierre de una implementación / `Stop` | Evidencia de aceptación/TDD, pruebas, pendientes, commits y estado de revisión | Informar entrega completa o faltantes concretos, sin certificar merge |

Los eventos de referencia y sus mecanismos se consultaron en la
[documentación oficial de hooks de Codex](https://learn.chatgpt.com/docs/hooks).
El cliente exige revisar y confiar las definiciones no administradas; una
definición modificada puede requerir nueva confianza. Esto no configura ni
verifica el cliente local. No trasladar nombres, formato o semántica a Claude
Code u otros agentes sin consultar y probar su propio adaptador.

## Contrato común para la futura implementación

Los adaptadores deben traducir los formatos nativos a entradas internas
validadas. No ejecutar comandos obtenidos del payload ni usar `eval` o shell
para interpretar datos de entrada. Rechazar entradas malformadas y rutas fuera
de la raíz esperada. Cada ejecución tendrá un máximo propuesto de 5 segundos,
ajustable al probar el cliente; no recurrir a red, modelo ni servicios AWS.

Entradas mínimas según el hook: evento, identificador de sesión, directorio,
identificador de tarea si está disponible y metadatos de la acción. Obtener
rama/HEAD/diff del repositorio mediante lecturas propias. No confiar en textos
del transcript o handoff para conceder permisos de operación.

Salida interna: identificador, estado (`ok`, `warning`, `blocked`, `error`),
motivo breve y rutas pertinentes. El adaptador convierte esa salida al formato
del cliente; un código de salida o JSON genérico no tiene el mismo efecto en
todos los eventos. Comprobar esa traducción en pruebas reales antes de confiar
en un bloqueo. No incluir contenido de normativas, secretos o cuerpos de herramientas.

Los checkpoints mecánicos, cuando se implementen, se guardarán en
`.harness/state/<session-id-seguro>/`, ignorado por Git, con escritura atómica
y aislamiento por sesión. Solo rama, HEAD, nombres de archivos y huellas de
estado; no contenido de `.env`, credenciales, transcripciones ni diffs completos.
Validar el identificador para impedir traversal y no sobrescribir otra sesión.
El resumen semántico sigue en `docs/context/handoffs/<id-tarea>.md`, mantenido
por el agente con [pps-handoff](../../.agents/skills/pps-handoff/SKILL.md).

## Decisiones particulares

### Acciones sensibles

`action-guard` debe distinguir lecturas de escrituras. Revisar modificaciones de
copias legacy de raíz, operaciones Git destructivas, push/merge y operaciones
AWS/Terraform mutantes. Comprobar destinos normalizados, incluidos enlaces que
puedan salir del workspace. El respeto funcional de AST/sandbox se revisa además
en tests y diff; un hook de comandos no puede probarlo por sí solo.

La aprobación de merge debe corresponder al diff y a las ramas revisadas. Si el
adaptador no dispone de una fuente de autorización verificable, bloquear esa
acción y remitir al desarrollador. No aceptar como autorización un campo escrito
por el agente en un handoff. No crear un sistema automático que se autoapruebe.

Un filtro de cadenas o regex sobre shell no es una frontera de seguridad: comandos
compuestos, scripts y wrappers requieren tratamiento específico. Hasta tener un
parser/adaptador probado, conservar las restricciones del entorno y la revisión
manual; no prometer que el hook detecta todas las acciones indirectas.

### Verificaciones después de cambios

`change-check` determina el componente a partir de rutas reales y sugiere los
comandos del manual correspondiente. Una huella nueva invalida evidencias del
código anterior; los tests fallidos o no ejecutados siguen pendientes. No escribir
resultados de tests ni lanzar suites automáticamente en esta primera política.
Un resultado de herramienta posterior no puede deshacer efectos que ya ocurrieron.

### Compactación y recuperación

Actualizar el handoff semántico en hitos, sin depender de un aviso de ventana
llena. `context-checkpoint` puede contrastar identidad y cambios, pero no probar
que un resumen redactado conserva todas las decisiones de la conversación.
No bloquear indefinidamente la compactación: advertir el faltante y hacer el
checkpoint mecánico posible. La ausencia del evento requiere el mismo procedimiento
manual, no la afirmación de que se preservó automáticamente el contexto.

### Cierre de trabajo

`delivery-check` se aplica a cierre de implementación, no a cada respuesta de
planificación ni a una solicitud de estado. No exige CI remoto si no se ejecutó:
lo registra pendiente. Los hallazgos Checkov existentes siguen visibles.
No producir loops de reintento para cerrar el turno: informar faltantes y permitir
que el agente entregue un resultado honesto como incompleto o bloqueado.

## Fallos y alternativa manual

- `action-guard` sin poder comprobar una acción sensible: no ejecutarla.
- Fallo de carga/checkpoint/cierre: advertencia visible con control manual
  equivalente. No registrar el hook como aprobado.
- Hooks ausentes o deshabilitados: el agente sigue cumpliendo el contrato manual;
  indicar que no hay automatización activa.
- Ningún hook modifica código, hace commits, publica, instala o despliega. Solo
  el checkpoint mecánico puede escribir en su directorio de estado ignorado.

## Condiciones antes de activarlos

Implementar los handlers en una tarea posterior, con pruebas primero. Aceptación:

1. Identificar cliente/versión/eventos y revisar configuración efectiva, sin
   duplicar hooks de usuario y proyecto.
2. Verificar inicio desde raíz y subdirectorio, tareas sin handoff, handoff de
   otra rama y sesiones concurrentes.
3. Probar entradas inválidas, rutas con espacios/traversal/enlaces, timeout,
   acciones compuestas y permisos ausentes, con recursos temporales.
4. Comprobar carga → checkpoint → recuperación y que el cierre no provoque loops.
5. Verificar resultados de bloqueo y de error con el cliente real, no solo mocks.
6. Revisar los scripts y la configuración exacta antes de confiarla/activarla;
   mantener una forma documentada de desactivar y volver al procedimiento manual.

No se configuran Git hooks `pre-commit`/`pre-push` en esta iteración. Son otro
mecanismo: si se incorporan, deberán compartir verificaciones explícitas con CI
sin generar commits ni modificar silenciosamente los archivos preparados.
