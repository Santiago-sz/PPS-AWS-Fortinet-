---
name: pps-handoff
description: "Guardar o recuperar la continuidad de una tarea PPS mediante docs/context/handoffs/. Usar al retomar, alcanzar un hito, preparar compactación o dejar trabajo inconcluso; no para resumir conversaciones ajenas al proyecto."
---

# Continuidad PPS

Usar [el índice de contexto](../../../docs/context/README.md) y
[la convención de handoffs](../../../docs/context/handoffs/README.md).

Al retomar, identificar la tarea por solicitud, rama y handoff, sin elegir por
fecha únicamente. Leer instrucciones vigentes y comprobar Git: rama, HEAD,
índice y cambios. Si el relato difiere, corregir el contexto de la tarea antes
de continuar; el handoff no es una autorización vigente por sí mismo.

Al guardar, actualizar un archivo `<id-tarea>.md` y su entrada en el índice:

- Objetivo, aceptación, restricciones y estado de la tarea.
- Rama/base/último commit comprobados; cambios propios y preexistentes separados.
- Decisiones y fuentes relevantes, incluidas skills utilizadas.
- Etapa TDD, fallo inicial observado, pruebas ejecutadas y resultados reales.
- Pendientes, bloqueos y próximo paso ejecutable.
- Estado de revisión y merge: pendiente salvo aprobación explícita aplicable.

Marcar lo no comprobado. En tareas documentales, registrar sus comprobaciones
específicas en lugar de inventar una etapa TDD de código. No incluir claves,
volcados de entorno, transcripciones completas ni razonamiento interno.

Actualizar en hitos, no solo al agotarse el contexto. Al cerrar, trasladar el
conocimiento duradero al contexto o a decisiones y conservar el estado histórico
con fecha. La parte semántica la redacta el agente; los hooks solo pueden
preservar o comprobar estado mecánico conocido.
