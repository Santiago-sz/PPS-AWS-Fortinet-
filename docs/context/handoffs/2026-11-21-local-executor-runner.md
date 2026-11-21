# Ejecución local del executor para la primera prueba por VPN de usuario

- Fecha e identificador: 2026-11-21, local-executor-runner.
- Estado: implementado, verificado en local con tests y documentado. **No se
  ejecutó contra AWS ni contra un FortiGate.** La prueba real sigue pendiente.
- Rama: `feature/bedrock-knowledge-base`; commit de referencia al iniciar:
  `2927b58`, árbol limpio.
- Commits propios: `8edc38d` (script, tests, reglas de `.gitignore` y lint de
  `scripts/` en CI) y un commit documental posterior con esta guía y el resto
  de la documentación.
- Revisión del desarrollador y merge: pendientes. Push: no realizado.

## Objetivo y aceptación

El primer FortiGate real solo es alcanzable por una VPN de usuario (FortiClient)
desde una estación Windows; la Lambda `audit_executor` no llega a él. Se pidió
un camino para ejecutar la etapa del executor en esa estación, con la
generación en AWS:

- Entrada: `run_id` por argumento; bucket por `S3_BUCKET` o `--bucket`.
- Token solo por `FORTIGATE_TOKEN`; nunca por argumento, impreso, registrado ni
  escrito en disco.
- Mismo orden que la Lambda (hash, re-validación desde cero, sandbox),
  reutilizando los módulos existentes.
- Comprobación de conectividad previa que aborta con código distinto de cero.
- Reporte solo en un directorio local ignorado por Git; sin `put` a S3, SNS ni
  Secrets Manager.
- Advertencia visible cuando no existe `signal.setitimer`.
- Fuera del paquete de la Lambda. Sin escrituras al FortiGate.

## Restricciones y autorizaciones

- Sin `terraform`, sin llamadas reales a AWS, sin contacto con un FortiGate.
- Sin leer ni editar archivos `.env*`, `tfvars` ni estados.
- Sin tocar `lambda/` ni `terraform/` de la raíz.
- Commits locales autorizados en esta rama; sin push, merge ni cambio de rama.

## Diferencia con AGENTS.md

La sección 11 pide una rama por feature creada desde `master` y no mezclar
features. El encargo indicó de forma expresa permanecer en
`feature/bedrock-knowledge-base` y no cambiar de rama. Se siguió el encargo
(sección 7, punto 5: prevalece la solicitud vigente) y se deja registrada la
diferencia para que el desarrollador decida cómo integrar ambos trabajos.

## Decisiones

- **Ubicación**: `audit-engine/scripts/run_executor_local.py`.
  `infrastructure/pipeline/lambda.tf` empaqueta solo los `*.py` de
  `generator/`, `executor/`, `contracts/` y `legacy/`; `build_layer.py` solo
  instala dependencias de `layer-requirements.txt`. `scripts/` no entra en el
  ZIP ni en el layer.
- **`handler_executor.py` sin cambios**. El script repite la orquestación (unas
  pocas ramas) y reutiliza `s3_io`, `script_validator`, `sandbox`, `toolkit`,
  `fortigate_client` y los constructores de `reporter`. No duplica validación
  ni lógica del sandbox.
- **Comprobación de conectividad** con `client.get("system_global")`. El
  cliente convierte errores HTTP, TLS y de red en `None` y registra la causa;
  `None` se trata como fallo. El resultado queda memoizado en el cliente.
- **Punteros del manifest**: se exige que `run_id` coincida y que `script_key`
  esté bajo `artifacts/<run_id>/`, igual que `pps-api aws approve`.
- **Reporte local**: `audit-engine/local-runs/<run_id>/<fecha-hora-UTC>/`. El
  JSON agrega el bloque `execution` (`mode`, `runner`, `published`); el
  Markdown, una nota final. Son agregados: el archivo no se sube y nada lo
  consume desde S3.
- **Token**: se rechaza un valor con espacios o caracteres de control, sin
  mostrarlo. Un filtro de registro lo reemplaza por `[REDACTED]`, y el
  contenido del reporte se depura antes de escribirlo.
- **Códigos de salida**: 0 completo; 1 reporte escrito pero auditoría
  incompleta; 2 configuración o entrada; 3 conectividad.
- **CI**: `ruff` pasa a revisar `scripts/` completo en lugar de solo
  `scripts/build_layer.py`.

## Observación sobre código existente (sin modificar)

`http.client` incluye el valor del encabezado en el error que emite ante un
encabezado mal formado, y `FortiGateClient._get` registra el texto de esa
excepción. Un token con un salto de línea podría quedar en el registro de la
Lambda. El script local lo evita con la validación y el filtro; el cliente y la
Lambda no se tocaron. Queda como pendiente para evaluar.

## Skills

Ninguna skill del proyecto fue cargada; se siguieron `AGENTS.md` y el encargo.

## TDD y verificaciones

- Tests escritos primero en `audit-engine/tests/test_run_executor_local.py`.
  Fallo inicial observado: 35 errores, porque el script no existía.
- Implementación: 35 aprobados. Se agregaron después 2 tests de empaquetado.
- Resultado final (Windows, Python 3.12, `.venv`):
  - `pytest -q -p no:cacheprovider`: 501 aprobados, 1 omitido (464 + 37).
  - `ruff check generator/ executor/ contracts/ legacy/ tests/ evals/ scripts/`:
    sin observaciones.
  - `ruff format --check` sobre las mismas rutas: 48 archivos conformes.
  - `evals/run_evals.py --mode offline`: código de salida 0.
  - Ejecución del script sin variables de entorno: código 2 y mensaje con las
    tres variables faltantes, sin llamadas de red.
- No ejecutado: CI en Linux (sin push), `local-api`, `gui` y Terraform (no se
  modificaron).

## Pendientes y próximo paso

1. Realizar la prueba real siguiendo
   [la guía de ejecución local](../local-executor-run.md).
2. Comprobar el valor desplegado de `auto_execute`: con `true`, la Lambda se
   invoca sola y deja en S3 un reporte con hallazgos `indeterminate`.
3. Evaluar la observación sobre el registro del token en `FortiGateClient`.
4. Revisión del desarrollador y decisión de merge.
5. La arquitectura objetivo sigue siendo VPN Site-to-Site IPsec con el executor
   en una VPC.
