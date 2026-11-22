# Diagnóstico de solo lectura de la forma de las respuestas del FortiGate

- Fecha e identificador: 2026-11-22, fortigate-shape-diagnostic.
- Estado: implementado, verificado en local con tests y documentado. **No se
  ejecutó contra un FortiGate.** Falta ejecutarlo en la estación con la VPN.
- Rama: `feature/bedrock-knowledge-base`; commit de referencia al iniciar:
  `37bdbcf`. Árbol con dos archivos sin seguimiento en la raíz
  (`pps-reporte.json` y `pps-reporte 2.json`), del desarrollador: no se
  abrieron, agregaron, movieron ni borraron.
- Commits propios: `7673cfa` (script, módulo compartido, tests y conteo esperado
  en CI) y un commit documental posterior.
- Revisión del desarrollador y merge: pendientes. Push: no realizado.

## Objetivo y aceptación

Las dos corridas reales mostraron que los scripts generados tratan un dato
ausente como un valor (ver [status.md](../status.md)). Antes de cambiar el
toolkit hacen falta hechos del equipo. Se pidió una herramienta de solo lectura
que, para cada endpoint del catálogo, informe la forma de la respuesta:

- Mismo `GET` que el pipeline, a través del cliente existente donde sea posible.
- Solo estructura: si respondió, código HTTP, claves del sobre, tipo de
  `results`, cantidad de elementos y nombres de campo. Nunca valores.
- Sin acceso a AWS; mismo entorno que la ejecución local.
- Tabla en consola y `shapes.json` en un directorio ignorado por Git.
- Solo `GET`, acotado, con código de salida claro si falla la primera consulta.

La segunda parte del encargo, una propuesta de diseño para que el toolkit
garantice `indeterminate` ante datos ausentes o ilegibles, se entregó en el
informe de la tarea y no en el repositorio. No se implementó.

## Restricciones y autorizaciones

- Sin `terraform`, sin escrituras en AWS, sin contacto con un FortiGate.
- Lectura autorizada de los artefactos de las dos corridas en S3, descargados
  fuera del repositorio. No se copió ningún valor de los reportes locales a
  archivos con seguimiento.
- Commits locales en esta rama; sin push, merge ni cambio de rama. Se mantiene
  la diferencia con la sección 11 de `AGENTS.md` ya registrada en
  [el handoff de la ejecución local](2026-11-21-local-executor-runner.md).

## Decisiones

- **Ubicación**: `audit-engine/scripts/diagnose_fortigate_local.py`, fuera de
  las cuatro áreas que Terraform empaqueta. Un test lo comprueba para los tres
  scripts de estación.
- **Consulta propia con los datos del cliente**. `FortiGateClient._get` oculta
  el código HTTP y el sobre. El diagnóstico arma su `GET` con `base_url`,
  `headers` y `ssl_context` del cliente y el mismo tiempo de espera, sin tocar
  el cliente ni el comportamiento de la Lambda.
- **Errores por nombre de clase**. El texto de una excepción puede traer datos
  del equipo o encabezados; solo se informa su clase.
- **Nombres de campo y nombres de usuario**. Una clave se imprime solo si tiene
  forma de nombre de campo; un objeto cuyos valores son todos objetos se trata
  como mapa indexado por nombres y solo se cuentan sus entradas.
  `--counts-only` elimina todos los nombres. Es una heurística: no usa el
  esquema de FortiOS.
- **Versión**: se toma `version` y `build` del sobre de la primera respuesta,
  solo con el formato esperado. Nunca `serial` ni el nombre del equipo.
- **`--probe-global-scope`** (opcional): repite con `?scope=global` los
  endpoints que devolvieron una lista vacía. Es otra lectura `GET`, pensada
  para distinguir una tabla vacía de una tabla fuera del alcance del token.
- **Módulo compartido** `scripts/local_run_common.py`: lectura y validación del
  entorno del FortiGate, depuración del token y mensaje de equipo inalcanzable,
  extraídos de `run_executor_local.py` sin cambiar su comportamiento (sus 37
  tests siguen aprobando sin modificaciones).

## Skills

Ninguna skill del proyecto fue cargada; se siguieron `AGENTS.md` y el encargo.

## TDD y verificaciones

- Tests escritos primero en `audit-engine/tests/test_diagnose_fortigate_local.py`.
  Fallo inicial observado: 44 errores y 4 fallos, porque el script no existía.
- Se corrigieron dos expectativas de test que eran incorrectas (buscaban un
  nombre de campo que también es parte de una ruta del catálogo) y se agregó un
  test para los nombres de campo de la consulta con alcance global.
- Resultado final (Windows, Python 3.12, `.venv`):
  - `pytest -q -p no:cacheprovider`: 572 aprobados, 1 omitido (522 + 50).
  - `ruff check generator/ executor/ contracts/ legacy/ tests/ evals/ scripts/`:
    sin observaciones.
  - `ruff format --check` sobre las mismas rutas: 53 archivos conformes.
  - `evals/run_evals.py --mode offline`: código de salida 0.
  - Ejecución de ambos scripts sin variables de entorno: código 2 y mensaje con
    las variables faltantes, sin consultas de red.
- No ejecutado: CI en Linux (sin push), `local-api`, `gui` y Terraform (no se
  modificaron).

## Pendientes y próximo paso

1. Ejecutar el diagnóstico en la estación, con `--probe-global-scope`, según
   [la guía](../local-executor-run.md#10-diagnóstico-de-la-forma-de-las-respuestas),
   y revisar `shapes.json` antes de compartirlo.
2. Con esa salida, cerrar las preguntas abiertas de la propuesta de diseño y
   decidir su implementación.
3. Construir, a partir de `shapes.json`, el caso de regresión con datos de
   forma del equipo real.
4. Revisión del desarrollador y decisión de merge.
