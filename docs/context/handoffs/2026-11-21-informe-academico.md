# Organización del informe académico

- Fecha e identificador: 2026-11-21, informe-academico.
- Estado: estructura y contexto inicial creados; revisión del autor pendiente.
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
