# Organización del informe académico

- Fecha e identificador: 2026-11-21, informe-academico.
- Estado: estructura y contexto inicial creados; revisión del autor pendiente.
- Estado vigente: base documental integrada en `master`; continuación en
  `feature/informe-academico` desde `3d355bb`, según autorización posterior.
- Objetivo: conservar requisitos, investigación, evidencia, propuestas y contexto
  del informe académico en `/informe`, vinculados con el desarrollo del proyecto.
- Contexto de detalle y siguiente paso: [informe/contexto.md](../../../informe/contexto.md).
- Aceptación: carpeta navegable con fuentes, acuerdos y trazabilidad inicial;
  cambios de Google Docs sujetos a presentación y aprobación previa del autor.
- Rama encontrada: `feature/local-functional-validation`; HEAD `5b50e8d`;
  `master` local `96a99f7`. Árbol e índice inicialmente limpios.
- Cambios propios: `informe/`, este handoff y enlaces en índices documentales.
  No hay cambios preexistentes sin commit. No se cambió de rama ni se incorporó
  este trabajo a commits de validación funcional. No se creó otra rama mientras
  la integración anterior sigue pendiente según AGENTS.md, sección 11.
- Fuentes: informe Google Docs y reglamento aportados por el autor; instrucciones,
  contexto y handoff de validación funcional del repositorio.
- Skills de esta organización: pps-handoff y pps-review. La lectura previa del
  informe utilizó google-drive:google-docs.
- TDD: excepción documental; no hay comportamiento ejecutable modificado.
  Comprobaciones ejecutadas: 11 archivos Markdown y 67 enlaces locales sin
  errores; sin caracteres de reemplazo UTF-8; contenido y diff revisados;
  `git diff --check` correcto. No se ejecutaron pytest, evals ni Terraform.
- Autorizaciones: crear la estructura local y conservar contexto. No se aprueban
  por inferencia las responsabilidades propuestas, cambios remotos o merges.
- Pendientes: confirmar responsabilidades, diagnóstico por capítulo y matriz
  completa; resolver integración anterior antes de abrir otra rama de trabajo.
- Revisión y merge pendientes; sin commit ni push de este incremento.

## Incremento: requisitos de capítulos — 2026-11-21

- Pedido explícito: definir requisitos para todos los capítulos dentro de
  `informe/requisitos/`.
- Se añadieron trece fichas y se actualizaron índice, contexto y registro.
  Fuente reconsultada: arts. 22.4 y 24.3 del reglamento adjunto, páginas 9 a 15
  del PDF. Se separan temario obligatorio y criterios específicos del proyecto.
- Los archivos sin commit de la organización inicial ya existían al comenzar
  este incremento y se conservaron. Rama y HEAD sin cambios; sin nuevas
  operaciones Git de escritura.
- Skills: pps-handoff y pps-review, ya consultadas para esta tarea.
- Cumplimiento de Google Docs todavía sin comprobar por requisito; no hay
  aprobación ni carga de cambios en el documento.
- Pendiente: revisión del autor y diagnóstico por capítulo. Se mantiene la
  excepción documental de TDD; no hay cambios de código ejecutable.
- Verificación: 13 fichas y 53 requisitos únicos, referencias reglamentarias,
  apartados e índice completos; 21 Markdown y 84 enlaces locales sin errores;
  `git diff --check` correcto. Primer comando afectado por acentos en stdin de
  PowerShell; repetición con escapes Unicode aprobada, sin modificar requisitos.

## Publicación autorizada — 2026-11-21

- Solicitud expresa del autor: subir los cambios al repositorio.
- Alcance: commit documental y push a `origin/feature/local-functional-validation`
  de `/informe`, los índices y este handoff. La rama actual conserva sus commits
  anteriores de validación; no se crea otra rama ni se reescribe el historial.
- Se sustituye el estado anterior de conservar este incremento sin commit ni
  push. Merge en `master` y cambios en Google Docs siguen sin autorización.
- Revisar el índice, verificar enlaces y `git diff --check`, y comprobar que la
  referencia remota coincida con HEAD después del push. Resultado aún pendiente
  al redactar esta entrada previa al commit.
- Verificación previa al commit: 24 archivos Markdown y 121 enlaces locales
  comprobados; 13 capítulos y 53 requisitos únicos; `git diff --check` correcto.
- Resultado: `266b402` creado y publicado correctamente en
  `origin/feature/local-functional-validation`; seguimiento remoto configurado.
  La comprobación del índice detectó líneas vacías finales en las trece fichas;
  se corrigieron antes del commit y `git diff --cached --check` quedó limpio.
  Este resultado se guarda en un commit documental de seguimiento. Merge en
  `master` pendiente de autorización; Google Docs sin cambios.

## Merge autorizado y continuidad — 2026-11-21

- Autorización explícita del autor: merge a `master` y nueva rama para el informe.
- Origen integrado: `feature/local-functional-validation`, último commit
  `286c172`; destino: `master`, merge `3d355bb`, publicado en `origin/master`.
- Nueva rama: `feature/informe-academico`, creada desde `master` en `3d355bb`.
  Reutilizarla para continuar el informe. No hay cambios preexistentes pendientes.
- Limpieza realizada: rama anterior eliminada localmente con `git branch -d` y
  en el remoto, después de comprobar que sus commits estaban integrados y que
  esa integración estaba publicada en `origin/master`.
- Skills: pps-review y pps-handoff. Comprobaciones: fetch, sincronización de
  ramas, diff documental, merge sin conflictos, árbol idéntico al origen y
  comprobación de ancestros antes de la limpieza. No se modificó código ni se
  ejecutaron suites del producto para esta operación documental/Git.
- Esta entrada y el contexto registran el resultado desde la nueva rama. Merge
  futuro de sus cambios pendiente de revisión y autorización. Google Docs intacto.
- Próximo paso académico: confirmar responsabilidades del agente y revisar
  cumplimiento de requisitos por capítulo con propuestas previas a su carga.

## Revisión del capítulo I

Estado vigente: P-001 v3 incorpora las confirmaciones del autor sobre cronología, alcance y contribuciones institucionales. Próximo paso: revisión editorial de la versión completa.

Desde la base limpia `b262cff` de la rama del informe se consultó el capítulo y su tabla de diferenciales con Google Docs. La [propuesta P-001](../../../informe/propuestas/P-001-capitulo-i.md) reúne los seis requisitos, sus hallazgos y el reemplazo propuesto. Próximo paso: resolver las consultas con los autores y revisar la propuesta antes de cualquier carga. El cambio es documental y el merge está pendiente.
El autor resolvió la consulta de alcance. Continuar con P-001 v2 en informe/propuestas y consultar las atribuciones institucionales pendientes antes de cerrar el capítulo.

Al retomar, usar P-001 v6, pendiente de aprobación editorial. Incluye la función opcional del RAG, el ejemplo de verificación manual, el Golden Circle y la tabla de diferenciales contextualizada. Emplear «reporte» para los resultados exportables de PostureGuard. Para nuevas propuestas, partir de la [plantilla acordada](../../../informe/propuestas/plantilla.md).

Por pedido del autor, I.I de P-001 incorpora el apartado «Contexto real del proyecto (institucional, social y empresarial)» antes de I.II. El texto recoge el papel de ZConsulting y de la institución pública en las pruebas. La carga del capítulo completo en Google Docs sigue en pausa. Se usó la guía pps-handoff.

El autor autorizó la carga completa de P-001 v6. Se verificaron en la pestaña t.0 los 34 párrafos de I.I a I.V, las 15 celdas de la tabla 1 y ambas entradas bibliográficas. La paginación queda pendiente de revisión visual.

Se presentó [P-002 v1](../../../informe/propuestas/P-002-capitulo-ii.md) tras revisar II.I a II.VI en Google Docs. La encuesta corresponde al planteo cloud inicial. Quedan pendientes el respaldo de las diez respuestas, las fechas de aplicación, el cotejo de las figuras y la revisión editorial antes de la carga.

P-002 v2 incorpora la convocatoria interuniversitaria y las consultas a operadores FortiGate confirmadas por el autor. Se cotejaron las diez respuestas con Google Forms y se corrigió en la propuesta la frecuencia de reducción del tiempo de corrección (3 de 10). Pendientes la revisión visual de las figuras y la aprobación editorial.

P-002 v3 recupera las fuentes secundarias identificadas en II.I del informe y su uso en II.V. La revisión editorial y la carga siguen pendientes.

P-002 v4 incorpora en II.V la comparación de ocho alternativas cloud, su relación con la revisión de FortiGate y seis segmentos de organizaciones potencialmente beneficiarias. Pendiente de revisión y carga.

P-002 v5 precisa la participación del personal FortiGate, documenta las fuentes de la comparación, incluye seis leyendas y amplía la conclusión. Se guardó la preferencia de atribución en la guía del informe. Pendientes la revisión visual de las figuras y la carga aprobada.

P-002 v6 precisa las citas institucionales, el alcance de la muestra y el reporte por auditoría. La nota metodológica documenta las selecciones adicionales en las preguntas 5 y 9. La matriz distingue el diagnóstico inicial del estado actual. Sigue pendiente el cotejo visual de las seis figuras y la aprobación de la carga.

Se cotejaron visualmente las seis figuras originales con las leyendas de P-002 v6. R-02-04 queda cubierto. La figura 5 ya muestra el 30 % para reducir el tiempo de corrección. La carga sigue pendiente de aprobación.

Se cargó P-002 v6 con la aprobación del autor. El texto y las cuatro tablas coinciden con la propuesta. Las seis imágenes originales se conservaron junto a sus leyendas y se verificó la referencia de Fortinet en la bibliografía.

Se verificaron los títulos inmediatamente encima de las cuatro tablas del capítulo II en Google Docs (2.1 a 2.4) y se actualizaron las menciones en el texto, P-002 y la guía del informe.
