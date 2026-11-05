# Continuidad de tareas

Un handoff resume el estado verificable de una tarea para retomarla tras
compactación o cambio de sesión. No reemplaza las instrucciones actuales ni
autoriza acciones nuevas. Leer solo el que corresponda a la tarea y contrastarlo
con la rama, el commit y los cambios pendientes de Git.

| Tarea | Estado |
|---|---|
| [2026-11-05-reorganizacion-repositorio](2026-11-05-reorganizacion-repositorio.md) | Arquitectura implementada y verificada localmente; CI remoto pendiente |
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
