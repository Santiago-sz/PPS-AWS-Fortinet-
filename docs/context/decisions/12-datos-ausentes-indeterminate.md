# 12 — Un dato ausente o ilegible termina en `indeterminate`

- Fecha: 2026-11-22.
- Estado: **implementada el 2026-11-22** en la rama `fix/toolkit-absent-data`,
  por encargo del dueño del repositorio. Verificada solo con tests: **no se
  volvió a ejecutar contra un equipo.** Revisión de los autores y merge
  pendientes. Lo construido y sus diferencias con el diseño están en
  [«Implementación»](#implementación-2026-11-22); el resto del documento es el
  diseño original y se conserva como antecedente.
- No sustituye ninguna decisión. Se apoya en el principio ya aplicado a
  `clause_ref` (decisión de diseño n.º 4 del pipeline): las propiedades de
  seguridad y trazabilidad las garantiza el toolkit, no el script generado.
- El diagnóstico (`audit-engine/scripts/diagnose_fortigate_local.py`) se ejecutó
  contra un equipo de laboratorio; sus resultados, informados en el encargo,
  están en «Implementación».

## En una frase

El toolkit registra qué datos pidió el script y no obtuvo, y convierte en
`indeterminate` todo `pass`, `fail` o `not_applicable` de un control afectado,
sin cambiar el validador.

## Implementación (2026-11-22)

### Evidencia que la motivó

Informada en el encargo, no observada por el agente que implementó. Equipo de
laboratorio con FortiOS 7.6.8, usuario de API con perfil
`super_admin_readonly`, diagnóstico ejecutado con `--probe-global-scope`:

| Endpoint | Respuesta | Lectura |
|---|---|---|
| `system/admin` | HTTP 200, lista vacía, también con `scope=global` | El equipo tiene al menos cuatro administradores: el dato no se observó |
| `system/api-user` | HTTP 200, lista vacía | El usuario de API que consulta existe: el dato no se observó |
| `vpn.ipsec/phase1-interface`, `user/radius` | HTTP 200, lista vacía | Tablas realmente vacías en ese equipo |
| `system/dhcp/server`, `system/snmp/sysinfo` | HTTP 400 | Ruta mal formada en el catálogo |

Consecuencia observada: los controles generados informaron `total_admins=0` y
`super_admin_accounts=[]` con estado `pass`. Una lista vacía no prueba por sí
sola que falte un dato; por eso la regla distingue los endpoints que no pueden
estar vacíos de los que sí.

### Regla implementada

Todo en `audit-engine/executor/toolkit.py`; `sandbox.py` solo crea el registro
y lo pasa a `fgt` y `report`. El validador y su lista de permitidos no
cambiaron, y el namespace del script tampoco.

1. `ReadLedger`: registro por corrida, compartido por `FgtCapability` y
   `ReportCapability`. Guarda nombres de endpoint, tipos de laguna y nombres de
   campo; nunca un valor leído.
2. `fgt.get` anota una laguna en tres casos:
   - `unreadable`: el cliente devolvió `None` (error HTTP, fallo de red o
     respuesta sin `results`). El script recibe una lista vacía en lugar de
     `None`, así no falla.
   - `empty_not_possible`: respuesta vacía de un endpoint de
     `NEVER_EMPTY_ENDPOINTS` (`admins`, `admin_profiles`, `interfaces`,
     `api_users`).
   - `missing_field`: el script pidió, con `d[k]` o `k in d`, un campo que
     falta en todos los objetos hermanos de esa respuesta (`TrackedDict`).
3. `report.finding` decide el estado final. Reúne las lagunas de los endpoints
   que el control declara: los de `checks[].endpoints` del manifest más los que
   el script pasa en `endpoints_used`. Si hay alguna, guarda
   `status = "indeterminate"`.
4. También queda en `indeterminate` un estado fuera de los cuatro permitidos y
   un control que declara endpoints y no leyó ninguno (`not_read`).
5. Un control que no declara ningún endpoint, ni en el manifest ni en el
   script, hereda todas las lagunas anotadas hasta ese momento en la corrida:
   sin declaración no se puede acotar de qué dato depende. El generador no
   obliga a declarar endpoints (`llm_client.py` usa `c.get("endpoints", [])`),
   así que el caso puede darse.

**Regla para `fail`.** Un `fail` con una laguna en un endpoint declarado
también pasa a `indeterminate`, igual que `pass` y `not_applicable`: el punto 7
del diseño lo establece así. No es silencioso: el hallazgo conserva
`reported_status = "fail"`, las lagunas y el motivo, y el reporte los muestra.
La pregunta 5 (conservar un `fail` establecido con otro endpoint que sí se
leyó) sigue abierta para los autores; con la atribución por endpoint el
toolkit no puede saber con cuál de los endpoints se estableció el resultado.

### Contrato del hallazgo

Tres claves aditivas, presentes solo cuando el toolkit intervino. Un hallazgo
sin lagunas conserva exactamente las claves y los valores anteriores, y un
reporte sin lagunas es idéntico byte a byte (lo fijan los tests de hash de
`test_reporter.py`).

| Clave | Contenido |
|---|---|
| `reported_status` | Estado que informó el script, si el toolkit lo cambió |
| `data_gaps` | Lista de `{"endpoint", "kind", "field"?}` |
| `status_reason` | Texto en español que nombra el endpoint y, si corresponde, el campo |

Un hallazgo con lagunas lleva `remediation = null`: sin el dato no hay
evidencia que respalde una propuesta.

Presentación: `reporter.py` agrega la sección «Datos no disponibles» al
Markdown y una línea al aviso de SNS; el evento `executor_result` suma
`data_gap_count`. La API local ya conservaba claves desconocidas y su
exportación Markdown ahora imprime el motivo. La aplicación muestra el motivo
en el detalle del control y no presenta la propuesta del manifest para un
hallazgo con `data_gaps`.

Los scripts ya generados y guardados en S3 obtienen el comportamiento nuevo sin
regenerarse: la regla vive en el toolkit que los ejecuta.

### Rutas del catálogo

`system/dhcp/server` y `system/snmp/sysinfo` pasaron a `system.dhcp/server` y
`system.snmp/sysinfo`: una ruta `cmdb` de varios niveles se escribe con punto y
una sola barra antes del nombre de la tabla, como `vpn.ipsec/phase1-interface`
y `log.syslogd/setting`. Verificación: la forma `system.dhcp/server` figura en
la documentación pública de una biblioteca de terceros
([fortigate-api](https://fortigate-api.readthedocs.io/en/latest/fortigateapi/cmdb/system_dhcp/server.html));
`system.snmp/sysinfo` se dedujo de la misma convención y de la orden
`config system snmp sysinfo` de la referencia de la CLI. No se consultó la
referencia de la API de Fortinet (FNDN requiere cuenta) ni se probó contra un
equipo.

### Diferencias con el diseño

| Diseño | Implementado | Motivo |
|---|---|---|
| Subclases de `dict` y de `list` | Solo `TrackedDict`; las listas son `list` comunes | La respuesta se envuelve completa al leerla, así que recorrer, cortar u ordenar una lista conserva el seguimiento sin otra clase |
| `endpoints_read` en cada hallazgo | No se agrega | Habría cambiado la forma de todos los hallazgos, incluidos los que no tienen lagunas. Un control que no leyó nada de lo declarado queda marcado con `not_read` |
| Sin clave para el motivo | Se agrega `status_reason` | El encargo pide un motivo legible que nombre el endpoint |
| Suprimir la remediación en `reporter.py` | Se anula en el toolkit | Un solo lugar cubre el Markdown, el JSON, la API local y la aplicación |
| Atribución por endpoint declarado o por ventana, a elegir | Por endpoint declarado, con el punto 5 de la regla para los controles sin declaración | Es la variante que el diseño propone para empezar. No se midió cuántos `indeterminate` de más produce |
| Cambio de prompt como decisión aparte | No se cambió el prompt | Cambiarlo obliga a regrabar las evaluaciones en vivo (`evals/README.md`), lo que requiere llamadas a AWS no autorizadas en esta tarea. La garantía no depende del prompt |
| Regresión con `shapes.json` y los dos scripts reales | No se hizo | Los scripts y la salida del diagnóstico no están en el repositorio. Los tests usan las formas informadas en el encargo y scripts que imitan los modismos de los reales |

Cambio de contrato para los scripts: `fgt.get` ya no devuelve `None`. Un script
que comprobara `is None` sigue por la rama de datos presentes y el toolkit
corrige el estado. Por ese motivo se actualizó un test existente
(`test_handler_executor.py`, tolerancia a un endpoint inalcanzable): el control
del endpoint ilegible deja de ser una nota y pasa a ser un hallazgo
`indeterminate`; el control del endpoint que sí se leyó conserva su `fail`.

### Pendiente

- Repetir una corrida contra el equipo de laboratorio y comprobar los estados.
- Medir la proporción de `indeterminate` con los scripts reales (pregunta 8).
- Aprobación de `NEVER_EMPTY_ENDPOINTS` por los autores (pregunta 7).
- Supuesto A1 (una lectura `cmdb` devuelve todos los campos del esquema): sin
  confirmar. Si no se cumple, la regla `missing_field` degrada de más, nunca de
  menos.
- Copias con `dict(x)`: el acceso sobre una copia del nivel superior no se
  registra (pregunta 10).
- Preguntas 5, 6 y 9.

### Pregunta abierta: por qué `system/admin` llega vacío

Sin resolver. Un usuario de API con perfil `super_admin_readonly` recibió una
lista vacía de `system/admin` y de `system/api-user`, con y sin
`scope=global`. Que el resultado no cambie con `scope=global` no respalda la
hipótesis H2 (alcance de VDOM). La hipótesis H1 (esas tablas solo son visibles
para el perfil `super_admin` completo) es compatible con lo observado, pero
**no está verificada**: falta el experimento de repetir la lectura con otro
perfil. Hasta entonces el toolkit trata esas respuestas vacías como dato no
observado, sin suponer la causa.

## Problema

Dos corridas reales contra un FortiGate (2026-11-21 y 2026-11-22) mostraron
que los scripts generados tratan un dato ausente como un valor. Leyendo los
dos scripts y la forma de la evidencia de los reportes aparecen tres clases de
defecto distintas:

| Clase | Qué ocurre | Ejemplos observados |
|---|---|---|
| 1. Tabla vacía que no puede estar vacía | El equipo responde una lista vacía y el script la cuenta como «cero elementos» | Controles de administradores: cero administradores y, en la primera corrida, cero usuarios de API, con resultado `pass` |
| 2. Campo que la respuesta no trae | El script pide un nombre de campo que no existe en ese endpoint y usa un valor por defecto | Registro: `event` y `admin-log` (primera corrida), `admin` y `event` (segunda). FortiGuard: `update-schedule` y `status` |
| 3. Criterio incorrecto sobre datos leídos | El dato se leyó bien y la regla del script está mal | NTP: falla por no tener servidores propios aunque el tipo de sincronización se leyó |

La clase 3 no es un dato ausente. El toolkit no puede corregirla; corresponde
al prompt o a la base de conocimientos.

## Hechos comprobados leyendo el código y los scripts

- Ningún script usa `.get()`: el validador ya prohíbe todo acceso con punto
  salvo sobre `fgt` y `report` (`script_validator.py`, `_check_attribute`).
- Los valores por defecto se escriben como `d[k] if k in d else <valor>`
  (segunda corrida) o con una función auxiliar que devuelve `None` (primera).
- El propio prompt enseña ese modismo (`REDUCE_SYSTEM_PROMPT` en
  `llm_client.py`: `valor = d["clave"] if "clave" in d else None`) y no dice
  qué hacer cuando un dato falta.
- Ningún script comprueba si `fgt.get` devolvió `None`. Con un endpoint
  ilegible, `for x in None` o `len(None)` lanzaría una excepción y toda la
  corrida terminaría en `could_not_audit`. Las dos corridas terminaron en
  `completed`: todos los endpoints usados devolvieron `results` distinto de
  `None`.
- `ReportCapability.finding` (`toolkit.py`) guarda el estado que envía el
  script sin comprobar que sea uno de los cuatro permitidos, y confía en el
  `endpoints_used` que el script declara.
- Los scripts comparten datos entre controles: la segunda corrida lee
  `admins` una vez y lo usa en tres controles, y reutiliza valores derivados
  en controles posteriores. La primera usa una función por control.

## Opciones consideradas

| Opción | Qué resuelve | Resultado |
|---|---|---|
| (a) El toolkit registra, por control, los endpoints ilegibles o vacíos y degrada el resultado | Endpoints ilegibles | Necesaria, no suficiente: no detecta la clase 2 |
| (b) Envolver las respuestas para registrar el acceso a un campo que falta | Clase 2 | **Elegida**, solo en tiempo de ejecución |
| (b') Reglas del validador que prohíban los valores por defecto silenciosos | Clase 2, de forma estática | Descartada: el modismo es una expresión condicional con `in`, que también es código legítimo y que el prompt enseña. Aumentaría los rechazos y consumiría los tres intentos de generación (la segunda corrida ya necesitó dos) |
| (c) Propiedad «nunca vacío» por endpoint | Clase 1 | **Elegida** |
| (d) Solo cambios de prompt | Nada por construcción | Insuficiente sola: la segunda corrida «mejoró» mostrando `disable` para un campo ausente, que es peor. Útil como complemento |
| (e) Dar al generador el catálogo de campos de cada endpoint | La causa de la clase 2: el modelo no conoce los nombres de campo de FortiOS | Recomendada como paso posterior, con la salida del diagnóstico |

## Diseño original: (a) + (b) + (c), aplicado en `ReportCapability.finding`

Todo en `audit-engine/executor/toolkit.py`, sin agregar nodos, nombres ni
métodos a la lista de permitidos (regla 1 de `AGENTS.md`).

1. **Registro compartido.** Un objeto de registro común a `FgtCapability` y
   `ReportCapability`, creado en `sandbox.execute` (solo cableado).
2. **Resultado por endpoint.** `FgtCapability.get` anota si el endpoint resultó
   ilegible (el cliente devolvió `None`), vacío o correcto.
3. **Contenedores con seguimiento.** Los datos se devuelven envueltos en
   subclases de `dict` y `list`. `d[k]` y `k in d` anotan qué campo se pidió y
   si estaba. Siguen siendo `dict` y `list` para `isinstance`, `len`, `str`, la
   iteración, la comparación y el corte. El script no gana ninguna superficie:
   el acceso con punto ya está prohibido.
4. **Regla del campo que falta.** Pedir un campo es una laguna solo si ese
   campo falta en **todos** los objetos hermanos de esa respuesta. Un campo
   presente en algunos elementos y ausente en otros es opcional y no degrada.
5. **Endpoints que no pueden estar vacíos.** Un conjunto aparte,
   `NEVER_EMPTY_ENDPOINTS`, y no un tercer elemento en las tuplas de
   `ENDPOINTS`: `collect_all` del flujo legacy las desempaqueta de a dos y debe
   quedar idéntico. Candidatos: `admins`, `admin_profiles`, `interfaces` y
   `api_users` (el pipeline se autentica con un usuario de API, por lo que esa
   tabla no puede estar vacía para él).
6. **Endpoint ilegible.** Devolver un contenedor vacío marcado como ilegible en
   lugar de `None`, para que el script no falle y el control quede marcado.
7. **Aplicación.** Al registrar un hallazgo, si el control tiene alguna laguna
   y el script informó `pass`, `fail` o `not_applicable`, se guarda
   `status = "indeterminate"`, se conserva `reported_status` y se agrega
   `data_gaps` (endpoint, tipo de laguna y nombre de campo; nunca un valor).
   Además: un estado fuera de los cuatro permitidos pasa a `indeterminate`; un
   control del que no se leyó ningún endpoint declarado pasa a
   `indeterminate`; y se registra `endpoints_read`, observado por el toolkit,
   junto al `endpoints_used` que declara el script.

### A qué control se atribuye una laguna

Es la decisión de diseño que queda abierta.

| Variante | Ventaja | Costo |
|---|---|---|
| Por endpoint declarado: una laguna en un endpoint afecta a todo control que lo lista en `checks[].endpoints` del manifest | Correcta por construcción: la lista la resuelve el toolkit, no el script | Gruesa: un control que pide un campo inexistente en `firewall_policies` degradaría a los seis controles que usan ese endpoint |
| Por ventana: las lagunas anotadas entre dos llamadas a `report.finding` se atribuyen al hallazgo siguiente | Exacta cuando el script tiene una función por control | Deja pasar un control que reutiliza un valor derivado en una ventana anterior |

Se propone empezar por la primera y medir cuántos `indeterminate` de más
produce, repitiendo los dos scripts reales sobre datos de forma (ver el plan de
pruebas), antes de decidir si se afina.

## Cómo se distingue un ajuste opcional de un dato ilegible

La distinción descansa en un supuesto que el diagnóstico debe confirmar
(**A1**): una lectura `cmdb` de FortiOS devuelve todos los campos del esquema
de un objeto, con su valor por defecto cuando no están configurados. Si es
así, «sin configurar» aparece como un campo presente con `""`, `0`, `[]` o
`disable`, y una clave que falta significa que ese campo no existe en ese
endpoint o en esa versión. La regla «falta en todos los hermanos» mantiene el
diseño seguro aunque A1 se cumpla solo en parte.

Consecuencias:

- Una lista vacía en una tabla común (sin túneles IPsec, sin servidores NTP
  propios) sigue siendo una observación válida.
- El control de NTP sigue en `fail` en las dos corridas: necesita corregir el
  criterio, no el toolkit.

### Estimación sobre las dos corridas reales

Construida con los scripts y con la forma de la evidencia de los reportes
locales. No es una medición.

**Primera corrida (12 controles; 8 `pass`, 4 `fail`)**

| Control | Hoy | Propuesto | Motivo | Confianza |
|---|---|---|---|---|
| chk-0002 | pass | indeterminate | `admins` vacío | Alta |
| chk-0003 | pass | indeterminate | `admins` y `api_users` vacíos | Alta |
| chk-0007 | fail | indeterminate | `log_settings`: `event` y `admin-log` no vinieron | Alta |
| chk-0008 | pass | indeterminate | `fortiguard`: `update-schedule` no vino | Alta |
| chk-0006 | pass | indeterminate solo con atribución por endpoint | Lista `log_settings` pero no lee sus campos | Depende de la variante |

Resultado aproximado: 5 `pass`, 3 `fail`, 4 `indeterminate` (5 con la variante
gruesa).

**Segunda corrida (14 controles; 7 `pass`, 7 `fail`)**

| Control | Hoy | Propuesto | Motivo | Confianza |
|---|---|---|---|---|
| chk-0002 | pass | indeterminate | `admins` vacío | Alta |
| chk-0003 | pass | indeterminate | `admins` vacío | Alta |
| chk-0004 | fail | indeterminate | `admins` vacío (la parte de `local_users` sí se leyó) | Alta; ver pregunta 5 |
| chk-0007 | fail | indeterminate | `log_settings`: `admin` y `event` | Alta para `event`, probable para `admin` |
| chk-0009 | fail | indeterminate | `fortiguard`: `update-schedule` y `status` | Alta para el primero, probable para el segundo |
| chk-0005, chk-0011 | pass | indeterminate | Piden `ssl-min-proto-ver` en el nivel superior de los perfiles SSL/SSH | Suposición; lo decide el diagnóstico |
| chk-0010 | pass | indeterminate | Pide `zone` en las interfaces | Suposición; lo decide el diagnóstico |
| chk-0006 | pass | indeterminate solo con atribución por endpoint | Igual que en la primera corrida | Depende de la variante |

Entre 5 cambios casi seguros y 9 como máximo. No cambian chk-0001, chk-0008,
chk-0012, chk-0013 ni chk-0014.

La proporción es alta y es un retrato honesto: la mayor parte viene de nombres
de campo que el modelo inventa. Por eso la opción (e) importa tanto como el
cambio del toolkit.

## Consecuencias

| Área | Efecto |
|---|---|
| Lista de permitidos y corpus adversarial | Ninguno: no se agregan nodos, nombres, métodos ni reglas. `test_script_validator.py` no cambia. A revisar con los autores: los contenedores definen `__getitem__` y `__contains__` en código del toolkit, que se ejecuta cuando el script usa un subíndice |
| Contrato del manifest | Ninguno: usa `checks[].endpoints`, que ya existe |
| Contrato del reporte | Claves nuevas por hallazgo, aditivas: `reported_status`, `data_gaps`, `endpoints_read`. Los cuatro valores de estado no cambian. No se comprobó que la API local y la aplicación toleren claves nuevas: leer antes `gui/API_CONTRACT.md` |
| `reporter.py` | Hoy muestra la remediación de un `indeterminate` que la trae. Un control degradado por falta de datos mostraría una remediación sin evidencia: conviene suprimirla en ese caso. La tabla de hallazgos necesita mostrar el motivo |
| Evento del executor | `handler_executor._finish` puede sumar la cantidad de degradados; opcional |
| Evaluaciones y fixtures | El cambio del toolkit no las afecta: las evaluaciones offline repiten respuestas grabadas y no ejecutan scripts contra datos. Un cambio de prompt sí: `test_llm_client.py` fija los hashes de los prompts y las fixtures quedan desactualizadas hasta regrabarlas en vivo |
| Reintento acotado | Sin efecto por el toolkit, porque las reglas de validación no cambian. Solo (e), o una ejecución de prueba en el generador, agregarían reintentos |
| Flujo legacy | Sin cambios: `ENDPOINTS` conserva su forma; `collect_all`, `handler.py`, `analyzer.py` y las funciones legacy de `reporter.py` no se tocan |

Limitaciones conocidas del diseño:

- `dict(x)`, `list(x)` y `sorted(x)` son nombres seguros inyectados y devuelven
  copias comunes. Un acceso sobre una copia del nivel superior no se registra;
  los elementos anidados conservan el seguimiento. Cerrarlo exige reemplazar
  esos nombres en `sandbox.py`, lo que requiere una decisión de los autores.
- Una excepción en un script generado sigue descartando todos los hallazgos de
  la corrida. Es un defecto distinto, fuera de esta propuesta.

## Plan de pruebas

- `test_toolkit.py`: los contenedores se comportan como `dict` y `list` para
  todos los modismos de los dos scripts reales; solo se anota el acceso por
  clave de diccionario; «falta en todos los hermanos» contra «falta en
  algunos»; endpoints que no pueden estar vacíos; endpoint ilegible; degradación
  de `pass`, `fail` y `not_applicable`; estado desconocido; control sin ningún
  endpoint leído; `data_gaps` con nombres y nunca con valores.
- `test_sandbox.py`: cableado del registro; presupuestos y conteo de llamadas
  sin cambios.
- `test_reporter.py`: presentación del motivo; sin remediación para un control
  degradado por falta de datos; un reporte sin lagunas idéntico al actual.
- `test_handler_executor.py` y `test_run_executor_local.py`: de punta a punta
  con un cliente simulado que devuelve una tabla de administradores vacía y un
  objeto sin el campo pedido.
- **Regresión con el equipo real.** Una fixture construida con `shapes.json`
  (nombres de campo y tipos, con valores inventados del tipo correcto) y los
  dos scripts generados guardados como fixtures; se afirma el estado esperado
  de cada control con el toolkit nuevo. Sirve además para medir las dos
  variantes de atribución. Los scripts no contienen valores del equipo, pero
  incorporarlos al repositorio requiere el acuerdo de los autores.
- Las suites existentes siguen en verde sin debilitar ningún test.

## Tamaño y división en commits

Estimación: unas 350 líneas de código y 550 de tests. `toolkit.py`, entre 200
y 250; `sandbox.py`, entre 5 y 10; `reporter.py`, unas 40; `handler_executor.py`,
hasta 10; `llm_client.py`, unas 15 solo si cambia el prompt.

1. `feat(toolkit)`: registro y contenedores con seguimiento, solo anotando, sin
   cambiar los hallazgos.
2. `feat(toolkit)`: degradación por endpoint ilegible, lista de estados
   permitidos y endpoints observados por el toolkit.
3. `feat(toolkit)`: endpoints que no pueden estar vacíos.
4. `feat(toolkit)`: acceso a campos que faltan.
5. `feat(reporter)`: presentación de las lagunas y del estado informado.
6. `test`: regresión con la forma real y los dos scripts.
7. `feat(generator)`: indicaciones del prompt sobre datos ausentes, con los
   tests de hash actualizados (decisión aparte).
8. `docs`.

## Preguntas abiertas

Para el diagnóstico:

1. `admins` y `api_users`: código HTTP, tipo y cantidad de elementos, y qué
   devuelve la consulta con `scope=global`.
2. ¿Se cumple A1? En `shapes.json`, ¿`present_in` es igual a `item_count` para
   todos los campos de todos los endpoints de tipo lista?
3. Nombres de campo de `log_settings`, `fortiguard`, `ntp` (¿está `ntpserver`
   con una lista vacía?), `interfaces` (¿hay `zone`?) y `ssl_ssh_profiles`
   (¿dónde está la versión mínima de protocolo?).
4. ¿Falla algún endpoint para este perfil o esta versión?

Para los autores:

5. Si un endpoint declarado es ilegible pero un `fail` quedó establecido con
   otro que sí se leyó, ¿debe conservarse el `fail`?
6. ¿`not_applicable` debe poder degradarse?
7. Aprobación de la lista de endpoints que no pueden estar vacíos.
8. Atribución por endpoint o por ventana, después de ver los números de la
   regresión.
9. ¿Puede cambiarse el prompt ahora, sabiendo que obliga a regrabar las
   evaluaciones en vivo?
10. ¿Se cierra en el sandbox el hueco de las copias con `dict`, `list` y
    `sorted`?

## Por qué se leyeron cero administradores

**Comprobado.** Los dos scripts solo toman `len()` de lo que devuelve
`fgt.get("admins")` y lo recorren. `FgtCapability.get` pasa por
`FortiGateClient.get`, que devuelve `body.get("results")`. Un largo de cero sin
excepción significa que el equipo respondió HTTP 200 con `results` vacío. Un
401 o un 403 habrían producido `None` y la corrida habría abortado. Ni el
script ni el cliente están leyendo mal una respuesta con datos.

**Hipótesis principal (H1), no verificada.** Las tablas de administradores solo
son visibles para quien tiene el perfil `super_admin` completo. El perfil del
token es `super_admin_readonly`, que es otro perfil: el equipo filtra las filas
y devuelve una lista vacía con estado correcto.

**Alternativa (H2).** La consulta queda limitada al VDOM del token y esas
tablas pertenecen al alcance global.

Líneas del diagnóstico (ejecutado con `--probe-global-scope`) que lo deciden:

| Línea observada | Conclusión |
|---|---|
| `admins  system/admin  200  list  0  0  empty list` | Confirma la respuesta vacía del lado del equipo. Cualquier otra cosa (más de cero elementos, un objeto, un 4xx) refuta esta lectura y devuelve la atención a los scripts o a un cambio en el equipo |
| En esa misma línea, `scope=global: http 200, items N` con N mayor que cero | Confirma H2. La corrección está en cómo se pide esa ruta del catálogo |
| `scope=global: http 200, items 0`, o un 4xx | Apunta a H1. La corrección está en el perfil del equipo, o el endpoint se declara no observable y esos controles quedan en `indeterminate` |
| La línea de `api_users`, leída igual | Indica si ocurre lo mismo con los usuarios de API |
| `admin_profiles` con más de cero elementos | Caso de control: la primera corrida ya leyó una cantidad de perfiles distinta de cero |

## Fuentes

- Código: `audit-engine/executor/toolkit.py`, `sandbox.py`, `reporter.py`,
  `fortigate_client.py`, `handler_executor.py`;
  `audit-engine/contracts/script_validator.py`;
  `audit-engine/generator/llm_client.py`.
- Los dos scripts generados y sus manifests, leídos de S3 fuera del
  repositorio. No se copió ningún valor de los reportes locales.
- [Estado](../status.md) y
  [handoff del diagnóstico](../handoffs/2026-11-22-fortigate-shape-diagnostic.md).
