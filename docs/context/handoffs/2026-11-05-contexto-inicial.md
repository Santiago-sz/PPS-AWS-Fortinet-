# Handoff: primera iteración de contexto

- Fecha: 2026-11-05, America/Buenos_Aires.
- Tarea: `2026-11-05-contexto-inicial`.
- Estado: reorganización documental completada; contrato del agente en definición.
- Rama de referencia: `feature/fase1-harness-bedrock`.
- Commit de referencia: `e5ca5a7` (no se creó commit para esta tarea).

## Objetivo y aceptación

Mover la documentación existente de `docs/` a una carpeta `base` y utilizarla
para producir la primera iteración de contexto. Conservar documentos y diagramas,
mantener la navegación y distinguir antecedentes de hechos actuales.

La solicitud anterior de solo conversar fue ampliada por esta autorización
documental. No se autorizó implementar aún el contrato `AGENTS.md`, skills ni
hooks. No modificar código del producto ni revivir el runner de desarrollo
retirado durante la conversación.

## Estado previo y cambios propios

Preexistente: `.gitignore` tenía dos entradas agregadas a pedido del usuario,
`.harness/` y `.venv-harness/`; conservarlas.

Propios: trasladar ocho Markdown y doce archivos de diagramas a `docs/base/`,
crear el índice `docs/README.md` y los documentos de `docs/context/`.
Los manuales canónicos junto al código conservan sus ubicaciones.

## Acuerdos y fuentes

El usuario pidió definir reglas del agente, origen del contexto, skills, handoffs
y hooks. Acordó tests primero, con fallo inicial comprobado antes de implementar
comportamiento. Se propuso separar instrucciones (`AGENTS.md`) de conocimiento
(`docs/context/`) y procedimientos reutilizables (skills).

Se usaron los documentos `docs/base/README.md` y `01` a `07`, especialmente la
actualización WU 5 de `07-estado-y-pendientes.md`, que cierra P2, P5 y P11.
No asumir que la cuota o la infraestructura AWS siguen en ese estado.

No se aplicaron skills específicas para esta reorganización documental. En la
conversación previa se consultó `openai-docs` para estudiar hooks; eso no prueba
que estén configurados o disponibles en el cliente actual.

## Verificación y TDD

No se implementa comportamiento ejecutable. Las comprobaciones definidas antes
de mover archivos son: preservar los bytes originales, conservar todos los
diagramas, comprobar los enlaces Markdown locales y revisar el diff final.
Resultados al cierre, 2026-11-05:

- Veinte archivos originales trasladados, sin edición de su contenido.
  Los hashes calculados con los filtros Git de las rutas originales coinciden
  con HEAD; esa comparación normaliza los fines de línea de Windows.
- Sesenta y dos enlaces Markdown locales comprobados, todos con destino existente.
- `git diff --check` sin errores de whitespace.
- Pipeline: `275 passed, 1 skipped`, mediante
  `.venv-harness/Scripts/python.exe -m pytest -q -p no:cacheprovider`
  ejecutado desde `audit-pipeline/` usando la ruta relativa al entorno raíz.
- Evals offline: tres normativas, todos los umbrales cumplidos; salida 0.
- Sin cambios de código Python ni Terraform: no corresponde Ruff ni validación
  IaC por esta reorganización. No se ejecutaron operaciones AWS.

El entorno `.venv-harness/` preexistente se usó porque `.venv/` no estaba
disponible. Usarlo no reinstala el runner retirado ni activa hooks.

## Próximo paso

Retomar con el usuario la redacción de `AGENTS.md`: acordar agentes soportados,
selección/origen de skills y política de hooks. Incorporar TDD y continuidad al
contrato cuando el usuario autorice esa edición. Antes de actuar, comprobar Git
y releer su solicitud más reciente.
