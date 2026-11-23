# 13 — El generador recibe un catálogo de campos y no adivina nombres

- Fecha: 2026-11-22.
- Estado: **implementada el 2026-11-22** en la rama
  `feature/generator-field-catalog`, por encargo del dueño del repositorio.
  **Verificada solo con tests: no está desplegada, no se invocó al modelo con
  el prompt nuevo y no se ejecutó contra un equipo.** Revisión de los autores y
  merge pendientes.
- No sustituye ninguna decisión. Complementa la
  [decisión 12](12-datos-ausentes-indeterminate.md): aquella garantiza, al
  ejecutar, que un campo ausente termina en `indeterminate`; esta busca que el
  script pida campos que existen, para que esos controles tengan veredicto.

## En una frase

El generador entrega al modelo, como referencia, los nombres de campo
observados por endpoint en un equipo, y avisa dentro del ciclo de reintento
que ya existe cuando un script válido lee un campo que esa lista no tiene, sin
rechazarlo nunca por eso.

## Problema

Informado en el encargo; no observado por el agente que implementó. Dos
corridas reales contra el equipo de laboratorio (FortiOS 7.6.8), con el
toolkit de la decisión 12 ya desplegado:

| Endpoint | Campos que pidió el script y la respuesta no trae |
|---|---|
| `ssl_ssh_profiles` | `ssl-min-proto-ver` |
| `log_settings` | `admin`, `event` |
| `fortiguard` | `status`, `update-schedule`, `update-schedule-frequency` |
| `interfaces` | `zone` |

Resultado: entre 4 y 8 de 14 a 17 controles terminaron en `indeterminate`,
aunque el equipo tiene la información con otros nombres. El toolkit actuó
como debía; el defecto está antes, en los nombres que el modelo inventa.

Segundo problema, menor: una generación terminó `generation_failed` con
`failure_kinds_per_attempt: [["allowlist"],["allowlist"],["allowlist"]]` y
ningún registro decía qué construcción rechazó el validador. Un reintento
inmediato, con el mismo código, fue aceptado.

## Decisión

### 1. Catálogo versionado, solo con nombres

`audit-engine/generator/fortios_field_catalog.py` es un archivo generado. Por
cada clave de endpoint del toolkit guarda:

- `status`: `observed` o `unknown`;
- `shape`: `object`, `list` o `unknown`;
- `fortios_version`: la versión en que se observó (`null` si es `unknown`);
- `fields`: nombre de campo y, cuando el valor es un objeto o una lista de
  objetos, los nombres de un nivel anidado;
- `reason`, cuando es `unknown`: `not_answered`, `empty_list`, `no_fields` o
  `not_in_diagnostic`;
- `unlisted_field_count` y `fields_truncated`, copiados del diagnóstico.

Es un módulo `.py` y no un `.json` porque el paquete de la Lambda se arma con
`fileset(..., "*.py")` sobre `generator/`, `executor/`, `contracts/` y
`legacy/`: así viaja sin tocar `infrastructure/pipeline/lambda.tf`. Vive en
`generator/` porque solo el generador lo usa; el executor no lo importa y un
test lo fija.

Contenido al 2026-11-22: FortiOS v7.6.8 build 3744, 27 endpoints observados
con 1.499 nombres de campo y 467 nombres anidados (1.553 nombres distintos), y
4 endpoints `unknown`.

### 2. El catálogo en el prompt de reduce

`field_catalog.prompt_section()` arma el texto y `llm_client` lo agrega al
system prompt de reduce como `FIELD_CATALOG_SYSTEM_NOTE`, con o sin Knowledge
Base. `REDUCE_SYSTEM_PROMPT` y los prompts de map no cambian. El texto:

- declara la versión y el build de FortiOS de los que proviene;
- lista cada endpoint con su forma y sus campos (`campo{a, b}` para el nivel
  anidado) y marca «sin verificar» los `unknown`;
- fija las reglas: usar solo nombres listados para el endpoint; si el control
  necesita un dato que ningún campo listado expresa, no adivinar y registrar
  `indeterminate` con el motivo; un endpoint sin verificar se puede usar,
  leyendo cada campo de forma defensiva.

Va en el system prompt porque `bedrock_client` ya coloca un `cachePoint`
después de él: el texto depende solo del catálogo versionado, de modo que es
un prefijo fijo entre intentos y entre corridas.

Tamaño medido: la sección tiene 36.247 caracteres; el system prompt de reduce
pasa de 3.336 a 39.583 caracteres. En tokens es una estimación, no una
medición: entre 9.000 y 10.500 tokens más por llamada de reduce (36.247
caracteres a 4 y a 3,5 caracteres por token). El valor real se lee en
`input_tokens`, `cache_write_tokens` y `cache_read_tokens` del evento
`llm_call` de la primera corrida.

### 3. Aviso de campos no listados, dentro del ciclo que ya existe

Después de que `script_validator` acepta un script,
`field_catalog.find_unknown_field_references()` busca literales usados como
clave sobre datos del equipo que el catálogo no lista. Si encuentra alguno y
quedan intentos de `MAX_GENERATION_ATTEMPTS`, el intento siguiente lleva una
pista de corrección (campo, línea y endpoint de origen) en lugar del feedback
del validador.

**No es un rechazo.** Desde que existe un script válido, el resultado es
`ok`. La corrección se abandona, y se entrega el mejor script válido obtenido
(el de menos campos no listados), cuando:

- el intento siguiente no reduce la cantidad de campos no listados;
- el validador rechaza el intento de corrección;
- la llamada al modelo falla (por ejemplo, por límite de pedidos);
- se agotan los intentos.

Por construcción este cambio no puede producir un `generation_failed` que
antes no ocurría: las condiciones para llegar al primer script válido son las
mismas. Un script que conserva un campo inexistente se acepta como antes y el
toolkit deja ese hallazgo en `indeterminate` al ejecutar.

Heurística (prefiere no avisar antes que señalar código válido):

- Solo se mira `base["literal"]` en lectura. `"x" in d` no se mira: el prompt
  enseña esa forma también para buscar texto dentro de un valor
  (`"https" in iface["allowaccess"]`).
- `base` debe venir de `fgt.get("<endpoint>")`. El origen se sigue, sin orden
  de ejecución, por asignaciones, `for`, comprehensions, subíndices,
  parámetros y valores de retorno de las funciones del script. Sin origen
  conocido no se informa.
- Un diccionario armado por el script (`{...}`, comprehension de diccionario,
  `dict(...)`) no tiene origen, aunque copie valores del equipo; tampoco una
  variable a la que el script le asigna claves.
- Si el valor puede venir de un endpoint `unknown`, ausente del catálogo o con
  la lista truncada, no se informa.
- El literal debe tener forma de nombre de campo de esquema (minúsculas,
  dígitos, `-`, `_`). El diagnóstico no lista los nombres que no la tienen,
  así que un nombre de ese tipo no se puede juzgar.
- El nombre se busca entre los campos del endpoint y sus campos anidados, sin
  distinguir el nivel.

No detecta: claves pasadas por variable (`data[key]`), campos consultados solo
con `in` y datos que pasan por un diccionario del script.

Comprobación sobre los tres scripts de las fixtures grabadas de evals (son
anteriores a este cambio): informa 6 referencias, todas correctas al
compararlas a mano con el catálogo (`admintimeout` en `admins`; `min-length`
y `must-contain` en `password_policy`, que trae `minimum-length`;
`password-expire` en `admins`; `event` y `forward-traffic` en
`log_settings`), y ninguna sobre código válido. Tres scripts no alcanzan para
estimar la tasa de falsos avisos.

### 4. Registro

| Dónde | Qué |
|---|---|
| Evento `field_catalog_check` | Por intento aceptado por el validador: `attempt`, `fortios_version`, `unknown_field_references` y las primeras 20 `references` (`field`, `endpoints`, `line`) |
| Evento `field_correction_abandoned` | `attempt` y `reason` (`validator_rejected` o `model_call_failed`) |
| Evento `generation_result` | Agrega `reduce_calls`, `first_valid_attempt` y, si hubo script, `unknown_field_references` |
| Métrica `GenerationUnknownFieldReferences` | Cantidad del script entregado |
| Evento `generator_result` | `unknown_field_references` en `invoked` y `awaiting_approval` |
| Manifest, bloque aditivo `field_catalog` | `fortios_version`, `unknown_field_references`, `references` (hasta 20) y `reduce_calls` |

El bloque del manifest es informativo: el executor no lo lee. La API local y
la aplicación leen el manifest con `get` sobre claves conocidas y no se
modificaron. Todo lo registrado son nombres que escribió el script y claves de
endpoint; el generador no lee ningún dato de un equipo.

Cambios de significado que conviene conocer:

- `attempts` (resultado y manifest) y `attempts_used` (evento) son el intento
  que produjo el script entregado. Sin correcciones de campos coincide con el
  valor anterior.
- `GenerationAttempts` cuenta las llamadas de reduce hechas (`reduce_calls`).
- `GenerationFirstAttemptPass` conserva su significado: el validador aceptó el
  primer intento, aunque después se entregue una corrección posterior.

### 5. Qué rechazó el validador

Cada intento rechazado emite `generation_attempt_rejected` con `attempt`,
`failure_kinds`, `error_count` y hasta 10 `errors` (`rule_id`, `failure_kind`,
`message`, `line`, `col`), con los textos cortados a 200 caracteres. Son los
datos que el validador ya producía. No se registra el script ni un fragmento:
el mensaje de un error de sintaxis nombra la línea, no su contenido. El
validador no cambió.

## Límites

- **Una sola fuente.** El catálogo proviene de un equipo (FortiGate-VM de
  laboratorio), una versión (7.6.8) y los perfiles de administración con que
  se leyó. Otros modelos, versiones, licencias o funciones habilitadas pueden
  tener campos distintos. Un campo que solo aparece con cierta configuración
  puede faltar; el modelo recibirá la orden de no usarlo.
- **Lista por unión.** Para un endpoint de tipo lista, los campos son la unión
  de los objetos que había en el equipo ese día.
- **Cuatro endpoints sin verificar.** `dhcp_servers` y `snmp_sysinfo`
  respondieron HTTP 400 porque sus rutas estaban mal en ese momento
  (corregidas después, sin un diagnóstico nuevo). `vpn_ipsec` y
  `radius_servers` respondieron una lista vacía: no había objetos que
  observar. Ninguno tiene nombres en el catálogo; no se inventó ninguno.
- **Nombres no listados.** El diagnóstico omite las claves que no tienen forma
  de nombre de esquema: una en `interfaces`, `local_users`,
  `log_fortianalyzer` y `fortiguard`. El catálogo guarda la cantidad, no el
  nombre.
- **`admins` y `api_users`** se leyeron con un usuario `super_admin`; con
  `super_admin_readonly` llegan vacíos (decisión 12). El catálogo lista sus
  campos, pero el pipeline puede no verlos según el perfil del token.
  Observación del 2026-11-22 sobre el equipo de laboratorio (informada en el
  encargo y visible en el diagnóstico usado): para `system/admin` y
  `system/api-user`, leídos con `super_admin_readonly`, el sobre de la
  respuesta informa `matched_count` 1 mientras `results` es una lista vacía;
  las tablas realmente vacías informan 0. Es una observación de un equipo y
  una versión. No se usa en el código: `toolkit.py` no cambió por ella.
- **Efecto no medido.** Que el modelo siga la lista y que bajen los
  `indeterminate` es la hipótesis del cambio. Falta una corrida contra el
  equipo para comprobarlo.
- **Costo.** Cada llamada de reduce envía la sección completa. Una corrección
  de campos agrega hasta dos llamadas de reduce dentro del tope de tres.
- El catálogo no cambia `toolkit.py`: la garantía de la decisión 12 sigue
  siendo del toolkit, con los datos reales.

## Cómo regenerarlo

Desde `audit-engine/`, con el entorno de la raíz:

```bash
# 1. Diagnóstico de solo lectura contra el equipo (contacta el FortiGate).
../.venv/Scripts/python.exe scripts/diagnose_fortigate_local.py --probe-global-scope
#    Si `admins` y `api_users` llegan vacíos, repetir solo esos dos con un
#    usuario de API de otro perfil:
../.venv/Scripts/python.exe scripts/diagnose_fortigate_local.py --only admins,api_users

# 2. Construir el catálogo a partir de uno o más diagnósticos (sin red).
../.venv/Scripts/python.exe scripts/build_field_catalog.py \
    local-runs/diagnostics/<corrida-1>/shapes.json \
    local-runs/diagnostics/<corrida-2>/shapes.json

# 3. Revisar el diff de generator/fortios_field_catalog.py y correr los tests.
../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_build_field_catalog.py
```

El constructor rechaza un diagnóstico que no declare
`contains_device_values: false`, uno escrito con `--counts-only`, uno sin
versión de FortiOS y una mezcla de versiones distintas; conserva solo nombres
con forma de campo de esquema, y su salida es determinista (ordenada, sin
fecha). Un cambio del catálogo cambia el prompt de reduce: corresponde
regrabar las evaluaciones en vivo.

Un catálogo por versión de FortiOS no está contemplado: el archivo guarda una
sola. Si se audita otra versión, hay que decidir entre reemplazarlo o
seleccionar el catálogo por configuración.

## Opciones consideradas

| Opción | Por qué no |
|---|---|
| Volver obligatoria la lista (rechazar el script) | Aumentaría `generation_failed` y convertiría en error un catálogo incompleto. El toolkit ya trata el caso al ejecutar |
| Enviar solo los campos de los endpoints de cada control | El prompt dejaría de ser un prefijo fijo y perdería el caché; además el script puede leer cualquier endpoint |
| Poner el catálogo en el prompt de map | Map elige controles y endpoints; no escribe lecturas de campos |
| Tomar los nombres de la documentación de Fortinet | No había una fuente local verificable; el diagnóstico refleja lo que el equipo responde |
| Mirar también `"x" in d` | Señalaría búsquedas de texto dentro de valores, que el propio prompt enseña |

## Pendiente

1. Desplegar y repetir una auditoría contra el laboratorio; comparar la
   cantidad de `indeterminate` con las corridas del 2026-11-22.
2. Regrabar las fixtures de evals en vivo (ver `audit-engine/evals/README.md`).
3. Repetir el diagnóstico con las rutas corregidas para observar
   `dhcp_servers` y `snmp_sysinfo`, y regenerar el catálogo.
4. Decisiones de los autores: aceptar el costo en tokens o reducir la lista;
   qué hacer con otras versiones de FortiOS.

## Fuentes

- Encargo del 2026-11-22 (evidencia de las dos corridas y del
  `generation_failed`).
- Dos salidas `shapes.json` del diagnóstico contra el equipo de laboratorio
  (solo nombres, sin valores), no versionadas: una con los 31 endpoints leída
  con `super_admin_readonly` y otra con `admins` y `api_users` leída con
  `super_admin`.
- Código: `generator/llm_client.py`, `generator/field_catalog.py`,
  `generator/fortios_field_catalog.py`, `scripts/build_field_catalog.py`,
  `contracts/s3_io.py`, `generator/handler_generator.py`,
  `evals/run_evals.py`.
