# Guía de puesta en marcha desde cero y diseño de datos ausentes

- Fecha e identificador: 2026-11-22, puesta-en-marcha-desde-cero.
- Estado: documentación escrita, comprobada y registrada en commits. Revisión
  de los autores pendiente.
- Rama: `feature/bedrock-knowledge-base`; commit de referencia al iniciar:
  `b6c1bd8` (merge de `master` en la rama, hecho por el coordinador).
- Merge a `master`: según el encargo, el usuario lo autorizó el 2026-11-22 y lo
  ejecuta el coordinador después de este commit. Este agente no hizo push,
  merge ni cambio de rama.
- Archivos del desarrollador en la raíz (`pps-reporte.json`,
  `pps-reporte 2.json`): no se abrieron, agregaron, movieron ni borraron.

## Objetivo y aceptación

1. Un documento de entrada único para que otro agente, en otra PC con Windows
   y sin contexto, pueda instalar, verificar, demostrar y continuar el
   proyecto: [puesta-en-marcha-desde-cero.md](../puesta-en-marcha-desde-cero.md).
   Enlazado desde el `README.md` de la raíz, `AGENTS.md` y el índice de
   contexto.
2. La propuesta de diseño «dato ausente o ilegible termina en `indeterminate`»
   guardada en el repositorio como propuesta no implementada:
   [decisión 12](../decisions/12-datos-ausentes-indeterminate.md).
3. Cada comando comprobado contra el repositorio; los locales y de solo
   lectura, ejecutados.

## Restricciones y autorizaciones

- Sin `terraform`, sin escrituras en AWS, sin contacto con un FortiGate, sin
  leer archivos `.env*`, sin valores de un equipo real en archivos con
  seguimiento.
- Lecturas de AWS autorizadas por el encargo y ejecutadas para comprobar los
  comandos de la guía.

## Decisiones

- **Ubicación**: `docs/context/puesta-en-marcha-desde-cero.md`, junto al resto
  del contexto vigente.
- **Identificadores de la cuenta**: la guía no escribe el número de cuenta ni
  el identificador de la base de conocimientos. Los obtiene con comandos de
  lectura (`sts get-caller-identity`, `bedrock-agent list-knowledge-bases`). Los
  documentos del repositorio ya usaban marcadores en lugar de esos valores.
- **Marcas de verificación** `[V]`, `[I]` y `[NV]` en cada paso.
- **Diagrama en texto**: los documentos de `docs/` no usan Mermaid.
- **Formato**: se aplicó la skill `cognitive-doc-design` (camino rápido
  primero, tablas, resultado esperado por paso). La skill `runbook-forge` se
  cargó y no se aplicó: exige salida en inglés, una plantilla fija y no escribir
  el resultado en disco, lo que contradice las convenciones de este
  repositorio y el encargo.
- **Diseño como decisión 12 en estado «propuesta»**, según la convención de
  `decisions/README.md`.
- **Regla `/pps-reporte*.json` en `.gitignore`**: la aplicación propone ese
  nombre al exportar (`gui/pps_desktop/app.py`). Ningún archivo con seguimiento
  coincide con el patrón.

## Skills

`cognitive-doc-design` (aplicada) y `runbook-forge` (cargada, no aplicada).
Ninguna skill propia del proyecto.

## Verificaciones ejecutadas (2026-11-22, PC original)

- Suites: `audit-engine` 572 aprobados y 1 omitido; `local-api` 37 aprobados;
  `gui` 49 aprobados (Qt sin pantalla). `ruff check` del motor y de `gui` sin
  observaciones; evaluaciones offline de generación y de recuperación con
  código 0.
- Dependencias: `pip install --dry-run` de los archivos de requisitos y de
  `local-api[dev]` y `gui[dev]` en un entorno nuevo, sin errores. `pip check`
  confirma que `checkov` fija `boto3==1.35.49`.
- AWS, solo lecturas, en Windows PowerShell 5.1 y tal como figuran en la guía:
  identidad, tres Lambdas, tres buckets, base de conocimientos `ACTIVE`,
  trabajos de ingesta, entorno del generador, secreto, una consulta `retrieve`
  con sintaxis abreviada, listado y descarga de artefactos de una corrida a
  `%TEMP%`, lectura del manifest y del reporte de la Lambda.
- Sintaxis de `local-api/launch.py` (`serve`, `import-result`, `aws`) con
  `--help`; opción `--demo` de la aplicación, leída en el código.
- Enlaces relativos de los documentos tocados: sin enlaces rotos.

## No verificado

- Creación real del entorno virtual desde cero y el lanzador `py -3.12` (en la
  PC original ni `py` ni `python` están en el `PATH`).
- Clon nuevo desde GitHub.
- Apertura de la aplicación en una pantalla y el modo de demostración.
- La generación de una corrida nueva (escribe en AWS y tiene costo).
- La causa del reporte sin datos de la Lambda (`preparation_error:ValueError`):
  se atribuye al secreto con valor de relleno, sin haberlo leído.
- Si el laboratorio de `infrastructure/fortigate-lab` está desplegado.
- La ubicación exacta del estado y las variables de Terraform en la PC que
  desplegó.

## Pendientes y próximo paso

1. Revisión de la guía por los autores y, si corresponde, prueba real en la
   segunda PC; corregir en la guía lo marcado `[NV]`.
2. Construir el laboratorio FortiGate en AWS (sección 9 de la guía).
3. Ejecutar el diagnóstico y cerrar las preguntas de la decisión 12.
