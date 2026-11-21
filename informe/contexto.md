# Contexto del trabajo sobre el informe

Actualización: 2026-11-21. Estado: organización inicial y requisitos de los trece
capítulos definidos; revisión integral y configuración del agente pendientes.

## Objetivo y acuerdos del autor

El alcance confirmado por el autor es auditar la configuración de FortiGate con permisos de solo lectura y presentar propuestas de remediación. Las referencias a CSPM e IAM en la idea original se conservan como antecedentes. Este criterio guía el resumen, los objetivos, los capítulos técnicos y las conclusiones.

- Continuar el informe existente sobre el desarrollo del proyecto PPS/PIF:
  revisar, corregir y ampliar lo escrito.
- Usar el documento de Google Docs enlazado en el [índice](README.md).
- Cumplir los requisitos del reglamento RR 97/23 adjuntado por el autor.
- Presentar los cambios antes de cargarlos y esperar aprobación explícita.
- Guardar el contexto documental y su relación con el proyecto en `/informe`.
- Definir las tareas del agente antes de comenzar a trabajar con él. La
  propuesta de responsabilidades sigue pendiente de confirmación final; esta
  solicitud autoriza crear la carpeta y preservar el contexto.

## Responsabilidades propuestas para el agente

Revisar cumplimiento académico y coherencia entre capítulos; contrastar el
contenido con evidencia del desarrollo; proponer correcciones y ampliaciones;
revisar fuentes, bibliografía, figuras y formato; conservar trazabilidad y
continuidad. No modificar código ni operar infraestructura por una tarea de
documentación. No afirmar verificaciones que no se hayan realizado.

## Revisión preliminar ya realizada

El 2026-11-21 se consultó el informe mediante el conector Google Docs y se
visualizaron las 17 páginas del reglamento escaneado. Esa lectura permitió
identificar requisitos y hallazgos preliminares; no constituye una auditoría
integral del contenido ni del formato renderizado del informe.

- El resumen y varias secciones describen CSPM/IAM de alcance amplio y
  remediación automática. El capítulo IX describe auditoría FortiGate de solo
  lectura con remediaciones propuestas, consistente con el contrato del repo.
  Debe proponerse cómo explicar la evolución del alcance sin borrar antecedentes
  pertinentes ni presentar capacidades futuras como implementadas.
- Se identificaron capítulos I a XI. No se identificaron capítulos XII
  (Lecciones Aprendidas) y XIII (Entregables), exigidos por el reglamento.
- Se debe revisar numeración: aparecen dos apartados III. IV. y una sección
  VI.I. después de VI. II. Su corrección aún no está propuesta ni aprobada.
- El formato completo, la bibliografía y los índices requieren comprobación.

No se ha cargado ningún cambio en Google Docs durante esta tarea.

## Relación con el desarrollo

Los autores sitúan el origen en las PPS de 2026 en ZConsulting y la incorporación de Santiago Guglielmone en el segundo cuatrimestre. El RAG motivó acotar el contexto de referencia a FortiGate. Se utiliza «institución pública» para el ámbito que facilitó las herramientas y donde se realizaron las pruebas. El personal de redes y ciberseguridad revisa políticas cuya nomenclatura desigual dificulta localizarlas.

El proyecto audita FortiGate a partir de normativas PDF/DOCX mediante generación
Bedrock, validación estática y sandbox; sus remediaciones son recomendaciones.
Fuente de límites: [AGENTS.md](../AGENTS.md). Consultar el
[mapa de evidencia](evidencia/README.md) antes de redactar resultados.

El recorrido local GUI/API tiene evidencia histórica automatizada y confirmación
manual del usuario del 2026-11-16. Utiliza resultados sintéticos: no acredita una
auditoría real con Bedrock/FortiGate. No se han repetido esas pruebas para esta
tarea ni se ha comprobado aquí el entorno AWS actual.

## Estado mecánico al crear la carpeta

- Rama encontrada: `feature/local-functional-validation`.
- HEAD: `5b50e8d`; `master` local: `96a99f7`.
- Árbol e índice inicialmente limpios; integración de la tarea local pendiente.
- No se crea otra rama ni se hace merge o push. La estructura del informe queda
  sin commit para no incorporarla a los commits de la validación funcional.
- Antes de abrir una nueva rama, resolver el flujo de integración conforme a la
  sección 11 de AGENTS.md; el pedido documental no autoriza el merge anterior.

## Publicación en Git solicitada — 2026-11-21

El autor solicitó subir los cambios al repositorio. Esto autoriza un commit
documental y el push a `origin` de la rama actual
`feature/local-functional-validation`, sin merge en `master`, cambio de rama
ni reescritura de historial. La rama conserva los commits de validación local
anteriores; los cambios del informe se agrupan en un commit propio. La
autorización de push reemplaza la decisión inicial de mantener estos archivos
sin commit. El resultado de la publicación debe comprobarse contra el remoto.

Publicación inicial completada: commit `266b402` subido correctamente a
`origin/feature/local-functional-validation`, con seguimiento remoto configurado.
El registro de esta publicación se conserva en un commit documental posterior.
El merge estaba pendiente de autorización al cerrar esa publicación; se completó
por pedido posterior del autor, según el estado vigente que sigue.

## Rama vigente y merge autorizado — 2026-11-21

- El autor autorizó integrar la rama anterior en `master` y abrir una rama para
  continuar el informe. No se autorizaron cambios en Google Docs por este pedido.
- Merge sin conflictos: `3d355bb`, desde `feature/local-functional-validation`
  en `286c172` hacia `master`; integración publicada en `origin/master`.
- Rama actual del informe: `feature/informe-academico`, creada desde `master`
  en `3d355bb`. Continuar esta tarea en esa rama, sin abrir otra por sesión.
- Se comprobó que todos los commits de la rama anterior estaban integrados en
  `master` y publicados en `origin/master`; después se eliminó la rama anterior
  localmente con borrado seguro y en el remoto, conforme a AGENTS.md, sección 11.
- Las referencias anteriores a falta de autorización o archivos sin commit
  describen etapas históricas. Los nuevos cambios del informe requieren su
  propia revisión antes de otro merge; la aprobación no se extiende a ellos.

## Continuación del trabajo académico

Se añadieron fichas de requisitos para los capítulos I a XIII a pedido del
autor; consultar el [índice de requisitos](requisitos/README.md). Separan el
temario reglamentario de los criterios de revisión específicos de PostureGuard.
No se marcaron requisitos como cumplidos ni se editó Google Docs.

La revisión comenzó por el capítulo I. La [propuesta P-001](propuestas/P-001-capitulo-i.md)
contiene el diagnóstico de los seis requisitos y la redacción para revisión del autor.
