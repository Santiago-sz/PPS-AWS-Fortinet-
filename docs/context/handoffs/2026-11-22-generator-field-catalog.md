# Catálogo de campos para el generador (decisión 13)

- Fecha e identificador: 2026-11-22, generator-field-catalog.
- Estado: implementado y documentado. **Verificado solo con tests y con el
  modelo simulado. No está desplegado, no se invocó a Bedrock con el prompt
  nuevo y no se ejecutó contra un FortiGate.**
- Rama: `feature/generator-field-catalog`, creada desde `integration/lab-demo`
  en `30c2960`, en un árbol de trabajo aislado. Sin cambios preexistentes. La
  base no es `master` por indicación expresa del encargo.
- Commits propios, en orden: `26a557e` (catálogo y constructor), `cf92188`
  (sección del prompt y detección), `73fc810` (prompt de reduce, pista de
  corrección y registro de rechazos), `21d63b7` (manifest y evento terminal),
  `9c4ec7b` (evals), `76b2027` (test de empaquetado), `8d90fe2` (referencias
  técnicas y normativas) y un commit documental posterior.
- Revisión del desarrollador y merge: pendientes. Push: no realizado. No se
  tocó ninguna otra rama.

## Objetivo y aceptación

1. Que el generador deje de inventar nombres de campo: en dos corridas contra
   el laboratorio, entre 4 y 8 de 14 a 17 controles terminaron en
   `indeterminate` por campos que la respuesta no trae (informado en el
   encargo).
2. Que quede registrado qué rechazó el validador cuando una generación falla
   (una terminó `generation_failed` con tres rechazos `allowlist` sin detalle).
3. Agregado durante la tarea: que una fuente técnica de la base de
   conocimientos no aparezca en el reporte como si fuera normativa.

Aceptación pedida: catálogo versionado solo con nombres, determinista,
empaquetado en la Lambda y regenerable; catálogo en la parte fija del prompt
con la versión de FortiOS; aviso de campos no listados dentro del ciclo de
reintento existente, **sin** rechazo nuevo; registro estructurado del rechazo
sin el cuerpo del script; sin debilitar ninguna regla del harness y sin
cambiar la semántica de `toolkit.py`.

## Restricciones y autorizaciones

- Sin llamadas a AWS ni a Bedrock, sin contacto con un FortiGate, sin
  `terraform`.
- Lectura autorizada de exactamente dos archivos fuera del árbol de trabajo:
  las salidas `shapes.json` de los diagnósticos `20261123T010405Z` y
  `20261123T010735Z` del equipo de laboratorio (solo nombres). No se leyó nada
  más de `audit-engine/local-runs/`, ni `.pps-api/`, `pps-reporte*.json`,
  `.env*`, `*.tfvars` o estado de Terraform.
- Commits locales con Conventional Commits y sin atribución; sin push ni merge.

## Decisiones

El diseño, los límites y la forma de regenerar el catálogo están en la
[decisión 13](../decisions/13-catalogo-de-campos-generador.md); la separación
de referencias, en la
[actualización de la decisión 11](../decisions/11-referencias-en-generacion.md#actualización-del-2026-11-22-referencias-técnicas-y-normativas).
Lo elegido donde el encargo dejaba una opción:

- **Catálogo como módulo `.py` en `generator/`**, no `.json` en `contracts/`:
  el ZIP de la Lambda solo incluye `*.py`, y así no se toca `lambda.tf`.
- **Catálogo completo en el system prompt de reduce**, antes del `cachePoint`
  que ya existía. No se filtra por los endpoints de cada control para no
  perder el prefijo fijo.
- **`unknown` también para `vpn_ipsec` y `radius_servers`** (lista vacía en el
  laboratorio), además de `dhcp_servers` y `snmp_sysinfo` (HTTP 400).
- **La detección solo mira `base["literal"]`** con origen conocido en
  `fgt.get`; no mira `"x" in d`.
- **La corrección se abandona** si no reduce los campos no listados, si el
  validador rechaza el intento o si la llamada al modelo falla; siempre se
  entrega el mejor script válido. El último caso no estaba en el encargo: sin
  él, un fallo de transporte durante una corrección habría convertido un
  éxito en un fallo.
- **`attempts` pasa a ser el intento que produjo el script entregado**;
  `reduce_calls` cuenta las llamadas hechas y `first_valid_attempt` conserva
  el significado de `GenerationFirstAttemptPass` y de `first_attempt_pass` en
  evals.
- **Referencias**: la regla de clasificación vive en
  `contracts/reference_kinds.py` y el reporte clasifica por la clave del
  documento. `toolkit.py` no se tocó, así que `report.json` no trae `kind`.

## Skills

Ninguna skill del proyecto fue cargada; se siguieron `AGENTS.md` y el encargo.

## TDD y verificaciones

- Tests escritos antes que el código en cada incremento. Fallos iniciales
  observados:
  - `test_build_field_catalog.py`: error de importación por el módulo
    inexistente (no cuenta como fallo de comportamiento); sus 34 casos se
    observaron en verde recién con el constructor y el catálogo generado.
  - `test_field_catalog.py`: escrito antes del módulo; primera corrida ya con
    el módulo, 39 aprobados. El fallo inicial no se observó por separado.
  - `test_llm_client.py`: 23 fallos de comportamiento (prompt sin catálogo,
    sin pista de corrección, sin evento de rechazo).
  - `test_handler_generator.py` y `test_s3_io.py`: 4 fallos (bloque del
    manifest y evento).
  - `test_evals_offline.py`: 1 fallo, que además corrigió una expectativa
    propia equivocada: la detección encontró 3 campos no listados en la
    fixture de contraseñas que una revisión rápida previa había pasado por
    alto.
  - Referencias: 11 fallos en `test_reference_context.py`,
    `test_reporter.py` y `test_handler_generator.py`.
- Tests existentes que cambiaron de contrato de forma deliberada:
  - `test_llm_client.py`: el system prompt de reduce ahora es
    `REDUCE_SYSTEM_PROMPT + FIELD_CATALOG_SYSTEM_NOTE` (más la nota de
    referencia con la Knowledge Base). Los hashes de `REDUCE_SYSTEM_PROMPT`,
    del prompt de map y del prompt de usuario de reduce no cambiaron.
  - `test_reference_context.py` y `test_handler_generator.py`: las
    referencias del manifest llevan `kind`.
  - `test_reporter.py`: las fuentes bajo `fortinet/` se esperan en la sección
    técnica.
- Resultado final (Windows, Python 3.12, `.venv` del clon principal):
  - Motor, `pytest -q -p no:cacheprovider`: 755 aprobados, 1 omitido
    (620 + 135).
  - `ruff check generator/ executor/ contracts/ legacy/ tests/ evals/ scripts/`:
    sin observaciones. `ruff format --check` sobre las mismas rutas: 60
    archivos conformes.
  - `evals/run_evals.py --mode offline`: código de salida 0, con el aviso de
    fixtures anteriores al catálogo (ver abajo).
  - `evals/run_evals.py --suite retrieval --mode offline`: código de salida 0.
  - API local: 53 aprobados. Aplicación, con `QT_QPA_PLATFORM=offscreen`: 67
    aprobados. `ruff check` sin observaciones en ambas. Ninguna de las dos se
    modificó.
  - Observación: en una de cinco corridas de la suite de la API local hubo 1
    fallo (52 aprobados, 59 s en lugar de unos 12 s). No se registró qué test
    falló y no se reprodujo en las tres corridas siguientes. Ese código no se
    tocó en esta rama; queda como posible test sensible al tiempo.
- No ejecutado: CI en Linux (sin push), Terraform y Checkov (no se tocó
  `infrastructure/`), evaluaciones en vivo, ninguna llamada al modelo y
  ninguna corrida contra un equipo.

## Medidas

- Catálogo: FortiOS v7.6.8 build 3744; 27 endpoints observados, 1.499 nombres
  de campo y 467 anidados; 4 endpoints `unknown`.
- Prompt: la sección del catálogo tiene 36.247 caracteres. El system prompt
  de reduce pasa de 3.336 a 39.583 caracteres. Estimación, no medición: de
  9.000 a 10.500 tokens más por llamada de reduce.
- Detección sobre los tres scripts grabados de evals: 6 referencias, todas
  verificadas a mano contra el catálogo, ninguna sobre código válido.

## Evals

Las fixtures de `evals/recorded/` son anteriores al catálogo y no se
regrabaron. En offline cada normativa pide una llamada de corrección que la
fixture no trae; el ciclo conserva el script válido y la normativa termina
`ok`. El runner lo informa (`unknown_field_references`,
`reduce_calls_unanswered` y un aviso en la salida). Comando para regrabar, a
cargo del dueño:

```bash
cd audit-engine
AWS_PROFILE=pps-tesis AWS_REGION=us-east-1 ../.venv/Scripts/python.exe evals/run_evals.py --mode live --record
```

Entre 6 y 12 llamadas a Converse (tres normativas, 1 de map y de 1 a 3 de
reduce cada una); estimación de peor caso del runner: unos 113.000 tokens.

## Pendientes y próximo paso

1. Desplegar el generador y repetir una auditoría contra el laboratorio;
   comparar los `indeterminate` con las corridas del 2026-11-22 y leer
   `unknown_field_references` en el manifest.
2. Regrabar las evals en vivo con el comando de arriba y revisar el diff.
3. Leer en el primer `llm_call` de reduce los tokens reales del prompt
   (`input_tokens`, `cache_write_tokens`, `cache_read_tokens`).
4. Repetir el diagnóstico con las rutas corregidas de `dhcp_servers` y
   `snmp_sysinfo` y regenerar el catálogo.
5. Si vuelve a ocurrir un `generation_failed`, leer el evento
   `generation_attempt_rejected` de cada intento.
6. Decisiones de los autores: aceptar el costo en tokens o reducir la lista;
   tratamiento de otras versiones de FortiOS; si `report.json` debe llevar
   `kind` (exige tocar `toolkit.py`); prefijos técnicos del bucket.
7. Revisión del desarrollador y decisión de merge.
