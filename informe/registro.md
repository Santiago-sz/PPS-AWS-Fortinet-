# Registro de trabajo del informe

Conservar entradas fechadas con trabajo realizado, fuentes, decisiones,
propuestas, aprobaciones, cargas y pendientes. No guardar transcripciones
completas. Este registro describe acciones; no concede autorizaciones nuevas.

## 2026-11-21 — Organización inicial

- El autor identificó el informe en Google Docs y el reglamento RR 97/23.
- Solicitó revisar, corregir y ampliar el informe, presentando los cambios
  antes de su carga. Solicitó además crear `/informe` y conservar allí el
  contexto relacionado con el proyecto, la investigación y el trabajo realizado.
- Se consultó el informe mediante Google Docs y se visualizaron las 17 páginas
  escaneadas del reglamento. No se modificó el documento remoto.
- Se identificaron contradicciones de alcance y ausencia aparente de capítulos
  XII/XIII. Son hallazgos preliminares pendientes de diagnóstico integral.
- Se creó el índice, el contexto y las áreas de requisitos, investigación,
  evidencia y propuestas, con información inicial y pautas de trazabilidad.
- Se vinculó la evidencia local GUI/API del proyecto sin presentarla como E2E.
- Configuración del agente: pendiente. Responsabilidades propuestas: pendientes
  de confirmación final. Propuestas de texto aprobadas: ninguna. Cargas: ninguna.
- Control documental ejecutado: 11 archivos Markdown y 67 enlaces locales
  comprobados sin errores; sin caracteres de reemplazo UTF-8. Diff revisado y
  `git diff --check` correcto. No corresponde TDD de código ni ejecutar suites
  de componentes en este incremento.
- Rama encontrada: `feature/local-functional-validation`; estos archivos quedan
  sin commit y sin cambio de rama. Merge y push no autorizados.

Próximo paso: confirmar el alcance del agente y preparar diagnóstico por capítulo
y matriz de cumplimiento antes de proponer correcciones de texto.

## 2026-11-21 — Requisitos de todos los capítulos

- Solicitud: definir dentro de requisitos el contenido de todos los capítulos.
- Se reconsultaron visualmente las páginas 9 a 15 del PDF escaneado, que incluyen
  los arts. 21 a 24 y el temario detallado de los capítulos I a XIII.
- Se crearon trece fichas con requisitos identificados, referencia reglamentaria,
  aplicación a PostureGuard, evidencia necesaria y criterio de cierre.
- Se amplió el índice con enlaces a cada ficha y el procedimiento de seguimiento.
- Se distinguió el temario obligatorio de las recomendaciones del proyecto:
  Gantt, PERT e indicadores financieros específicos no se atribuyen al reglamento
  como técnicas exigidas por nombre.
- Los requisitos quedan pendientes de contraste con el documento vigente.
  No se elaboraron propuestas de texto ni se modificó Google Docs.
- Se mantienen los archivos de organización preexistentes sin descartar ni
  incorporar cambios ajenos; misma rama y sin commit, merge ni push.
- Excepción TDD documental: comprobar cobertura del temario, enlaces, contenido
  y diff. No corresponde ejecutar suites del producto.
- Verificación final: 13 fichas, 53 requisitos reglamentarios con identificadores
  únicos, cuatro apartados por ficha e índice completo; 21 archivos Markdown y
  84 enlaces locales comprobados sin errores; `git diff --check` correcto.
  La primera comprobación se detuvo por codificación de acentos en stdin de
  PowerShell; se corrigió el comando con escapes Unicode y la repetición pasó.

Próximo paso: diagnóstico por capítulo y matriz de cumplimiento con evidencia,
una vez confirmado el alcance de trabajo del agente.

## 2026-11-21 — Publicación solicitada en el repositorio

- El autor solicitó subir los cambios documentales al repositorio.
- Se prepara un commit propio con `/informe`, los tres índices modificados y
  el handoff de esta tarea, en la rama actual `feature/local-functional-validation`.
- Se autoriza push a `origin` de esa rama; no se autoriza merge en `master`,
  reescritura del historial ni edición de Google Docs.
- La rama incluye los commits anteriores de validación funcional. No se cambia
  su historia ni se publican otras ramas por este pedido.
- Comprobar identidad del commit remoto y limpieza del árbol después del push.
- Resultado: commit documental `266b402`, 24 archivos y 962 líneas añadidas,
  publicado correctamente en `origin/feature/local-functional-validation`.
  Se configuró el seguimiento remoto de la rama. La comprobación del índice
  detectó líneas vacías extra al final de las trece fichas; se corrigieron y
  `git diff --cached --check` pasó antes del commit. Sin merge en `master`.

## 2026-11-21 — Merge y nueva rama del informe

- El autor pidió merge en `master` y una nueva rama para trabajar el documento.
- Se actualizaron referencias remotas y se comprobó árbol limpio, rama anterior
  sincronizada y ausencia de commits remotos pendientes en `master`.
- Merge sin conflictos de `feature/local-functional-validation` (`286c172`) a
  `master`: `3d355bb`. Se publicó correctamente en `origin/master`.
- El árbol del merge coincide con el de la rama integrada; se comprobó el diff
  documental sin errores de espacios. No se cambió código ni se repitieron tests
  del producto: el incremento integrado es exclusivamente documental.
- Se creó `feature/informe-academico` desde `master` en `3d355bb`.
- Se verificó la integración de la rama anterior tanto localmente como en
  `origin/master` antes de eliminarla localmente con `git branch -d` y en GitHub.
- Se mantiene la regla de presentar y aprobar cambios antes de editar Google
  Docs. El trabajo nuevo en esta rama no tiene autorización anticipada de merge.

## 2026-11-21 — Revisión del capítulo I

Actualización: P-001 v3 incorpora las cuatro respuestas del autor sobre origen, RAG, revisión manual de políticas y anonimización. La versión completa espera aprobación editorial.

Se presentó [P-001 v1](propuestas/P-001-capitulo-i.md) con seis requisitos parcialmente cubiertos, revisión de la tabla 1 y texto propuesto para I.I a I.V. Pendientes de respuesta el alcance académico aprobado y la descripción de los vínculos institucionales. Carga en Google Docs pendiente de aprobación.

El autor confirmó el alcance de auditoría FortiGate con permisos de solo lectura y propuestas de remediación. P-001 v2 incorpora la decisión en el objetivo general. Su carga sigue pendiente de revisión.

El autor adoptó el formato de P-001 para las próximas propuestas. La [plantilla](propuestas/plantilla.md) conserva el diagnóstico inicial, muestra la cobertura de la versión propuesta y registra la aprobación editorial y la carga.

P-001 v4 incorpora la denominación «reporte» para el resultado de la auditoría en todo el texto propuesto del capítulo I.

P-001 v6 incorpora las mejoras solicitadas sobre RAG, objetivos, necesidad y estilo. Conserva el Golden Circle y las cuatro filas de la tabla de v5, incorpora la referencia del PNUD y vincula los diferenciales con la revisión manual. La aprobación editorial y la carga están pendientes.

Por pedido del autor se actualizó el Golden Circle de I.III en Google Docs. Se incorporaron la atribución del modelo, la cita del PNUD en I.IV y ambas entradas en Referencias. El resto de P-001 continúa pendiente de carga.

El autor autorizó la carga completa de P-001 v6. Se verificaron en la pestaña t.0 los 34 párrafos de I.I a I.V, las 15 celdas de la tabla 1 y ambas entradas bibliográficas. La paginación queda pendiente de revisión visual.

Se presentó [P-002 v1](propuestas/P-002-capitulo-ii.md) tras revisar II.I a II.VI en Google Docs. La encuesta corresponde al planteo cloud inicial. Quedan pendientes el respaldo de las diez respuestas, las fechas de aplicación, el cotejo de las figuras y la revisión editorial antes de la carga.

P-002 v2 incorpora la convocatoria interuniversitaria y las consultas a operadores FortiGate confirmadas por el autor. Se cotejaron las diez respuestas con Google Forms y se corrigió en la propuesta la frecuencia de reducción del tiempo de corrección (3 de 10). Pendientes la revisión visual de las figuras y la aprobación editorial.

P-002 v3 recupera las fuentes secundarias identificadas en II.I del informe y su uso en II.V. La revisión editorial y la carga siguen pendientes.

P-002 v4 incorpora en II.V la comparación de ocho alternativas cloud, su relación con la revisión de FortiGate y seis segmentos de organizaciones potencialmente beneficiarias. Pendiente de revisión y carga.

P-002 v5 precisa la participación del personal FortiGate, documenta las fuentes de la comparación, incluye seis leyendas y amplía la conclusión. Se guardó la preferencia de atribución en la guía del informe. Pendientes la revisión visual de las figuras y la carga aprobada.

P-002 v6 precisa las citas institucionales, el alcance de la muestra y el reporte por auditoría. La nota metodológica documenta las selecciones adicionales en las preguntas 5 y 9. La matriz distingue el diagnóstico inicial del estado actual. Sigue pendiente el cotejo visual de las seis figuras y la aprobación de la carga.

Se cotejaron visualmente las seis figuras originales con las leyendas de P-002 v6. R-02-04 queda cubierto. La figura 5 ya muestra el 30 % para reducir el tiempo de corrección. La carga sigue pendiente de aprobación.

Se cargó P-002 v6 con la aprobación del autor. El texto y las cuatro tablas coinciden con la propuesta. Las seis imágenes originales se conservaron junto a sus leyendas y se verificó la referencia de Fortinet en la bibliografía.

Se verificaron los títulos inmediatamente encima de las cuatro tablas del capítulo II en Google Docs (2.1 a 2.4) y se actualizaron las menciones en el texto, P-002 y la guía del informe.
