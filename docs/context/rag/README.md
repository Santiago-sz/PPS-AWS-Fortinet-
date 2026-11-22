# RAG con Amazon Bedrock: resumen de trabajo

Fecha: 2026-11-17; actualizado el 2026-11-18 y el 2026-11-21. Rama:
`feature/bedrock-knowledge-base`, creada desde `master` en `32e0ac5`. Estado:
implementado, desplegado y con el corpus cargado e indexado (ver las dos
secciones de estado que siguen). Revisión y merge pendientes.

Este documento resume lo realizado y sirve como punto de entrada para retomar
el trabajo. El detalle vive en una sola fuente por tema:

| Tema | Fuente de detalle |
|---|---|
| Módulo Terraform, costos, despliegue e ingesta | [README del módulo](../../../infrastructure/knowledge-base/README.md) |
| Documentos cargados, fuentes, condiciones de uso, conversiones y procedimiento de carga | [Manifiesto del corpus](corpus.md) |
| Decisión de diseño y alternativas descartadas | [Decisión 10](../decisions/10-bedrock-knowledge-base.md) |
| Uso de los fragmentos en la generación y trazabilidad | [Decisión 11](../decisions/11-referencias-en-generacion.md) |
| Evaluación de la calidad de recuperación | [README de evals](../../../audit-engine/evals/README.md) |
| Estado de la tarea, pruebas y pendientes | [Handoff](../handoffs/2026-11-17-bedrock-knowledge-base.md) |
| Contrato de entorno e IAM | [AGENTS.md](../../../AGENTS.md), sección 4 |

## Estado al 2026-11-21: corpus ampliado e índice sincronizado

A pedido del dueño del repositorio se cargaron los documentos de referencia
nuevos en el bucket de conocimiento y se ejecutó una ingesta. Fueron las
únicas escrituras en AWS: no se modificó la Knowledge Base, el origen de
datos, IAM ni ningún otro recurso, y no se ejecutó Terraform. Donde las
secciones siguientes describan el índice desfasado o el corpus sin definir,
vale lo que se indica aquí.

**Causa de los dos fallos de la primera ingesta.** El trabajo `93LXHYAEHA`
(2026-11-18) informa como único motivo «Connector run was stopped before this
document was processed»: los dos documentos no fallaron por su formato ni por
su tamaño, sino porque el trabajo se detuvo antes de procesarlos. No había
nada que convertir.

**Corpus.** 25 documentos, 24,45 MB, en seis prefijos (`fortinet/`, `nist/`,
`disa/`, `argentina/`, `espana/`, `propio/`). El detalle por documento está
en el [manifiesto del corpus](corpus.md). No se borró ningún objeto del
bucket.

**Ingesta.** Trabajo `R4MQ9D7QQZ`, iniciado el 2026-11-22 a las 01:14 UTC:

| Dato | Valor |
|---|---|
| Estado final | `COMPLETE`, a las 01:24 UTC (10 minutos) |
| Documentos examinados | 25 |
| Archivos de metadatos examinados | 3 |
| Documentos nuevos indexados | 23 |
| Archivos de metadatos aplicados a un documento ya indexado | 1 |
| Documentos modificados indexados | 0 |
| Documentos quitados del índice | 3 |
| Documentos fallidos | 0 |
| Documentos omitidos | 0 |

Los tres documentos quitados son las normativas de ejemplo
`propio/politica-*.md`, que se habían retirado del bucket el 2026-11-18 y
seguían en el índice. El estado por documento
(`list-knowledge-base-documents`) muestra los 25 documentos del bucket
indexados y esas tres claves como `NOT_FOUND`. `nist/NIST.CSWP.29-CSF-2.0.pdf`
figura como `IGNORED` porque ya estaba indexado y no cambió; una consulta lo
devuelve con normalidad.

**Recuperación comprobada** con consultas `Retrieve` de solo lectura (cinco
resultados pedidos; se anota el mejor puntaje de cada documento):

| Consulta | Documentos devueltos |
|---|---|
| «How is the minimum password length configured in the FortiOS system password policy?» | `fortinet/FortiOS-7.6.8-CLI_Reference-extracto.pdf` (0,64; los cinco resultados) |
| «restrict administrator access to trusted hosts trusthost on FortiGate admin accounts» | `disa/DISA-STIG-FortiGate-Firewall-NDM-V1R6.md` (0,85), `fortinet/FortiOS-8.0.0-Best_Practices.pdf` (0,63) |
| «configuracion de servidores NTP y sincronizacion horaria en FortiGate» | `propio/catalogo-endpoints-fortigate.md` (0,84), `disa/DISA-STIG-FortiGate-Firewall-NDM-V1R6.md` (0,69), `fortinet/FortiOS-7.6.8-CLI_Reference-extracto.pdf` (0,58) |
| «Decision Administrativa 641/2021 requisitos minimos control de accesos autenticacion de usuarios» | `argentina/DA-641-2021.html` (0,85), `argentina/BCRA-TO-Requisitos-minimos-riesgos-TI-SI.pdf` (0,67), `argentina/DA-641-2021-Anexo-I.pdf` (0,55) |
| «STIG FortiGate device must enforce account lockout after three consecutive invalid logon attempts» | `disa/DISA-STIG-FortiGate-Firewall-NDM-V1R6.md` (0,92) |
| «B.2.3 Verificar la identificacion y autorizacion: establecer una politica de contrasenas seguras, evitar el uso de usuarios genericos» | `argentina/Res-AAIP-47-2018-Anexos-I-II.pdf` (0,91) |

Además se obtuvo al menos un resultado de cada uno de los demás documentos
nuevos con una consulta propia de su tema (SP 800-52r2, SP 800-63B-4,
SP 800-77r1, SP 800-92, SP 800-113, las dos planillas de NIST, la STIG de
firewall, la Ley 25.326, la Resolución 44/2023, el Real Decreto 311/2022 y
la Disposición 1/2022). Los puntajes de la tabla son los obtenidos con el
trabajo ya terminado; el servicio devolvió a veces menos resultados que los
cinco pedidos.

Otros resultados:

- **Normativas de ejemplo retiradas.** Una consulta sobre política interna de
  contraseñas y acceso administrativo, que antes devolvía
  `propio/politica-*.md`, devuelve ahora el texto ordenado del BCRA y el Real
  Decreto 311/2022; ninguna de las consultas de esta sesión devolvió esas
  claves.
- **Anexos publicados como imágenes.** Los anexos de la Resolución AAIP
  47/2018, que Infoleg publica como imágenes, se recuperan por su contenido:
  la extracción de imágenes de la base leyó el texto de las tablas.
- **Filtro por `fortios_version`, probado por primera vez.** La consulta
  sobre *trusted hosts* con el filtro `equals` y el valor `7.6` devolvió solo
  `fortinet/FortiOS-7.6.0-Best_Practices.pdf` (0,85) y el extracto de la
  referencia de CLI (0,60). El filtro funciona dentro de
  `managedSearchConfiguration` y deja fuera todo documento sin el atributo.
- **Guía de 8.0.0.** Sin filtro, en la consulta sobre *trusted hosts*
  apareció la guía de FortiOS 8.0.0 y no la de 7.6.0. Su retiro es una decisión abierta
  (manifiesto, sección 7).

**No verificado en esta sesión:** la evaluación de recuperación en vivo
(`--suite retrieval --mode live`), cuyas fuentes esperadas siguen siendo
provisorias; el efecto del corpus nuevo sobre los scripts generados; y la
calidad de las respuestas sobre las planillas de NIST más allá de comprobar
que se recuperan. No se disparó el pipeline del generador ni se contactó
ningún FortiGate.

## Estado al 2026-11-18: desplegado y probado en AWS

Esta sección registra el despliegue y las pruebas reales. Donde las secciones
siguientes digan «no desplegado» o «sin verificar», vale lo que se indica
aquí.

**Desplegado** (cuenta del laboratorio, `us-east-1`, a pedido del dueño del
repositorio):

| Módulo | Resultado |
|---|---|
| `infrastructure/knowledge-base` | 9 recursos creados: bucket de documentos, rol de servicio, Knowledge Base administrada y origen de datos S3. `plan` posterior sin cambios |
| `infrastructure/pipeline` | Política `bedrock:Retrieve` del generador creada, tres Lambdas actualizadas en el lugar, capa del generador reemplazada. `plan` posterior sin cambios |

El identificador de la base se entrega al pipeline con un archivo
`knowledge_base.auto.tfvars` local, ignorado por Git.

**Documentos cargados** en el bucket de conocimiento (copia local fuera del
repositorio):

| Documento | Origen |
|---|---|
| `fortinet/FortiOS-8.0.0-Best_Practices.pdf` | Fortinet, público |
| `nist/NIST.CSWP.29-CSF-2.0.pdf` | NIST, público |
| `nist/NIST.SP.800-41r1-Firewalls.pdf` | NIST, público |
| `nist/NIST.SP.800-53r5.pdf` | NIST, público |
| `propio/catalogo-endpoints-fortigate.md` | Material propio: los 31 endpoints y qué se revisa en cada uno |

La guía de Fortinet es de FortiOS 8.0.0 porque la versión del equipo
institucional no fue informada; debe reemplazarse por la que corresponda.
(El 2026-11-21 se agregaron los documentos de la rama 7.6; la guía de 8.0.0
sigue en el bucket a la espera de una decisión sobre su retiro.)

**Ingesta, con un problema abierto.** La primera ingesta indexó 4 de 6
documentos y quedó detenida. Durante su ejecución se retiraron del bucket
tres normativas de ejemplo que no correspondían como material de referencia;
se pidió detener el trabajo y permaneció en estado `STOPPING`, lo que impide
iniciar otro. Consecuencias al cierre del día: los dos documentos NIST
agregados después no están indexados, y dos de las normativas de ejemplo
retiradas siguen en el índice y aparecen como fuente en las pruebas. Cuando
el trabajo termine, ejecutar una ingesta nueva.

**Problemas encontrados al probar en vivo y su corrección.** Hasta este día
el sistema nunca había llamado al modelo con éxito, por la cuota en cero.
Las primeras ejecuciones reales mostraron cinco fallas, todas corregidas con
tests escritos primero:

| Problema observado | Corrección | Commit |
|---|---|---|
| El modelo envuelve a veces el JSON de la fase map en un bloque de código; las tres normativas de evaluación fallaban | Se quita ese envoltorio antes de interpretar | `4c9f95d` |
| Los scripts generados se rechazaban en los tres intentos: el modelo usaba métodos de `dict`, `list` y `str` y cadenas `elif`, que el validador prohíbe y el prompt no mencionaba | El prompt de generación describe esos límites y las formas equivalentes. El validador y el sandbox no cambiaron | `1a7bbfb` |
| Con una normativa real, una respuesta de map llegó cortada por el tope de salida | Tope de map de 4.096 a 16.000 tokens y de reduce a 8.192; una respuesta cortada falla de forma explícita | `8bd93a5` |
| Dentro de la Lambda, las 16 consultas a la base fallaron con `ParamValidationError`: el SDK del runtime no conocía `managedSearchConfiguration` | La capa del generador fija una versión de boto3 | `d34f7d4` |
| Con la recuperación ya funcionando, solo 5 de 17 controles recibían referencia por los topes de tamaño | Topes de 3.000 a 10.000 caracteres por control y de 12.000 a 80.000 en total | `addaee8` |

**Evaluaciones en vivo del generador** (tres normativas de evaluación, modelo
Claude Sonnet 4.6): todos los umbrales cumplidos. Generación exitosa 1,00;
aprobación al primer intento 0,67; cobertura de controles entre 0,92 y 0,96;
precisión de endpoints 1,00; cobertura de remediación 1,00. Las fixtures
grabadas se regeneraron con respuestas reales del modelo.

**Auditoría de punta a punta** con una normativa real, el Anexo I de la
Decisión Administrativa 641/2021 (requisitos mínimos de seguridad de la
información para organismos del Sector Público Nacional), con la base
habilitada:

| Etapa | Resultado |
|---|---|
| Extracción de controles | 12 controles en 3 llamadas de map |
| Recuperación | 12 consultas, ninguna fallida; los 12 controles recibieron referencia; 3 fragmentos omitidos por el tope por control |
| Generación del script | Script válido al tercer intento |
| Manifiesto | Bloque `knowledge_base` con fuentes por control; sin identificador de cuenta ni nombre de bucket |
| Ejecución | `could_not_audit`, motivo `preparation_error:ValueError`: no hay un FortiGate conectado y el secreto del dispositivo conserva su valor de ejemplo |

En tres ejecuciones sobre la misma normativa el modelo extrajo 16, 17 y 12
controles. Esa variación es propia del modelo y conviene medirla.

**Sigue sin verificar:** el filtro por `fortios_version` (no hay documentos
con ese metadato), el efecto de la referencia sobre la calidad de los scripts
(con referencia se necesitaron tres intentos; sin ella, uno o dos en las
evaluaciones), la evaluación de recuperación en vivo (las preguntas y
fuentes esperadas siguen siendo provisorias) y la ejecución contra un
FortiGate real.

**Otros efectos del despliegue:** se recreó la suscripción de correo del
tema de notificaciones, que requiere confirmación del destinatario.

## 1. Qué es el RAG y para qué se usa aquí

RAG (generación aumentada por recuperación) consiste en buscar, antes de
invocar al modelo, los fragmentos de un conjunto de documentos que se
relacionan con una consulta, y entregarlos como contexto. Tiene dos etapas:

1. **Ingesta.** Cada documento se divide en fragmentos; un modelo de
   embeddings convierte cada fragmento en un vector que representa su
   significado; los vectores se guardan en un almacén vectorial junto con el
   texto y su origen.
2. **Consulta.** La pregunta se convierte en vector con el mismo modelo; el
   almacén devuelve los fragmentos más cercanos; esos fragmentos se agregan
   al prompt.

En Amazon Bedrock esto se implementa con una **Knowledge Base administrada**:
Bedrock gestiona la división, los embeddings y el almacén vectorial. La
consulta se hace con la operación `Retrieve`, que devuelve fragmentos con su
origen y puntaje.

**Límite que condiciona el diseño.** La recuperación devuelve lo más
parecido, no todo. Por eso el RAG **no reemplaza** el recorrido completo de la
normativa que hace el generador (map/reduce sobre todos los fragmentos): ese
recorrido garantiza que ninguna cláusula quede sin auditar y sostiene la
trazabilidad cláusula por cláusula. El RAG es una capa adicional que aporta
documentación de referencia para un control puntual, por ejemplo para elegir
el endpoint correcto o redactar una remediación.

## 2. Qué se construyó

| Componente | Ubicación | Estado |
|---|---|---|
| Módulo Terraform de la Knowledge Base (bucket de documentos, rol de servicio, base administrada, origen de datos S3) | `infrastructure/knowledge-base/` | Desplegado el 2026-11-18 |
| Enganche en el pipeline (variables, entorno del generador, permiso de consulta condicional; desde el 2026-11-18, `knowledge_base_fortios_version`) | `infrastructure/pipeline/` | Desplegado el 2026-11-18 |
| Módulo de recuperación, con filtro de metadatos opcional y configuración de búsqueda en una constante | `audit-engine/generator/knowledge_retriever.py` | Con tests |
| Referencia para la generación (2026-11-18): una consulta por control entre map y reduce, topes, sección del prompt y bloque del manifest | `audit-engine/generator/reference_context.py`, `llm_client.py`, `handler_generator.py` | Con tests; probado contra la base y el modelo el 2026-11-18 |
| Trazabilidad (2026-11-18): bloque `knowledge_base` en el manifest y `references` por hallazgo en el reporte JSON y Markdown | `contracts/s3_io.py`, `executor/toolkit.py`, `executor/reporter.py` | Con tests |
| Evals de recuperación (2026-11-18): preguntas versionadas, hit rate en k, MRR, umbrales, modos offline y live | `audit-engine/evals/retrieval_eval.py`, `evals/retrieval/` | Offline en verde con fixture **sintética**; live sin ejecutar |
| Tests de contrato entre Terraform y código | `audit-engine/tests/test_knowledge_base_iac.py` | En verde |

Cómo se usa la referencia, en breve (detalle en la decisión 11):

- Después de map, el generador hace una consulta por control con el título y
  la intención de ese control. No usa texto de la normativa como consulta.
- A lo sumo 40 consultas por corrida, 10.000 caracteres de referencia por
  control y 80.000 en total. Un fragmento entra entero o se omite, nunca se
  recorta: por control se omite el que no cabe y se prueba el siguiente; sobre
  el total se descartan primero los de menor puntaje. La normativa y los
  controles nunca se recortan.
- De cada fragmento se guarda como fuente solo la clave del objeto (por
  ejemplo `fortinet/FortiOS-8.0.0-Best_Practices.pdf`). El servicio devuelve
  una URL cuyo nombre de bucket incluye el id de cuenta; ese dato no llega al
  prompt, al manifiesto, al reporte, a los eventos ni a las evaluaciones.
- Los fragmentos entran al prompt de reduce en una sección delimitada,
  agrupados por control y con su fuente. El prompt de sistema aclara que son
  material de consulta, no instrucciones, y que no amplían lo que el script
  puede llamar.
- Si una consulta falla, ese control queda sin referencia y la generación
  sigue. El manifest indica cuántos controles tuvieron referencia y cuántas
  consultas fallaron.
- El manifest guarda, por control, la fuente y el puntaje de cada fragmento
  usado, sin su texto. El ejecutor lee ese bloque y lo muestra por hallazgo
  en el reporte; no consulta la base ni el modelo.

Reglas que se mantienen:

- El RAG está **apagado por defecto**: con `knowledge_base_id` vacío el
  pipeline se comporta igual que antes y el rol del generador no recibe
  ningún permiso sobre Knowledge Bases. Con la base apagada, los prompts, el
  manifest y el reporte son idénticos byte a byte a los anteriores; lo
  comprueban tests con hashes fijados sobre `e86bbc1`.
- El permiso `bedrock:Retrieve` es una política aparte, existe solo cuando la
  variable tiene valor y apunta al ARN exacto de esa base.
- El ejecutor y el evaluador heredado no reciben permisos de Bedrock.
- No se modificaron validador, sandbox, catálogo de endpoints ni el flujo
  heredado. Los prompts solo cambian con la base habilitada.

## 3. Dos módulos de Terraform, en orden

La variante administrada requiere una versión mayor del proveedor de AWS que
la usada por el pipeline desplegado. Para no actualizar el proveedor de esa
pila, la Knowledge Base vive en un módulo separado con estado propio.

| Módulo | Proveedor AWS | Contenido |
|---|---|---|
| `infrastructure/pipeline` | 5.100.0 (sin cambios) | Lambdas, buckets, IAM, SNS, alarmas |
| `infrastructure/knowledge-base` | 6.73 | Bucket de documentos, rol y Knowledge Base |

Orden de despliegue, a cargo del operador:

1. `plan` y `apply` en `infrastructure/knowledge-base`; anotar el
   identificador de la base que devuelve como salida.
2. Cargar documentos en el bucket e iniciar la ingesta.
3. Asignar ese identificador a `knowledge_base_id` en las variables del
   pipeline.
4. `plan` y `apply` en `infrastructure/pipeline`.

Los pasos detallados están en el README del módulo. Se ejecutaron el
2026-11-18; ver la sección de estado al inicio.

## 4. Verificaciones realizadas (2026-11-17, Windows)

| Verificación | Resultado |
|---|---|
| `pytest` en `audit-engine` | 350 aprobados, 1 omitido (antes: 283 y 1) |
| `ruff check` y `ruff format --check` | Sin observaciones |
| Evaluaciones offline | Código de salida 0; fixtures sin cambios |
| `terraform fmt`, `init -backend=false`, `validate` en ambos módulos | Aprobado |
| Checkov, pipeline | 118 aprobados, 29 fallidos (los mismos 29 previos) |
| Checkov, knowledge-base | 19 aprobados, 4 fallidos (hallazgos del bucket ya aceptados en el pipeline) |

El desarrollo siguió TDD: los tests se escribieron primero y se observó su
fallo antes de implementar. El detalle está en el handoff.

Verificaciones del incremento del 2026-11-18 (Windows):

| Verificación | Resultado |
|---|---|
| `pytest` en `audit-engine` | 460 aprobados, 1 omitido (antes: 350 y 1) |
| `ruff check` y `ruff format --check` | Sin observaciones |
| Evaluaciones offline de generación | Código de salida 0; fixtures grabadas sin cambios |
| Evaluaciones offline de recuperación | Código de salida 0 sobre fixture sintética |
| `terraform fmt`, `init -backend=false`, `validate` en el pipeline | Aprobado |
| Checkov, pipeline | 118 aprobados, 29 fallidos (sin cambios) |

El módulo `infrastructure/knowledge-base` no se tocó ni se volvió a validar en
ese incremento.

Integración continua: el commit `e86bbc1` aprobó los cinco jobs en Linux
([run 44227778670](https://github.com/Santiago-sz/PPS-AWS-Fortinet-/actions/runs/44227778670),
informado el 2026-11-18). El incremento del 2026-11-18 todavía no pasó por
integración continua.

## 5. Qué está verificado contra el servicio y qué no

Comprobado contra la base desplegada el 2026-11-18 (prueba hecha fuera de
este trabajo de código, que no llamó a AWS):

- **Configuración de búsqueda.** Una base administrada rechaza
  `vectorSearchConfiguration` (`ValidationException: ... is not supported for
  managed knowledge bases. Use managedSearchConfiguration instead.`) y acepta
  `managedSearchConfiguration` con la cantidad de resultados. El código usa
  `managedSearchConfiguration` (`SEARCH_CONFIGURATION_KEY` en
  `knowledge_retriever.py`).
- **Forma de los resultados.** Cada resultado trae puntaje, texto y una
  ubicación de tipo S3 cuyo URI es una URL
  `https://<bucket>.s3.amazonaws.com/<clave>`, no `s3://`.
- **Cantidad y tamaño.** Pedir 3 resultados devolvió 2. Para una consulta se
  observaron fragmentos de 9.943, 1.463, 1.109 y 1.082 caracteres.

Sin verificar:

- El código de este incremento ejecutado contra la base y contra el modelo.
- **El filtro por `fortios_version`.** El modelo de servicio de botocore
  1.43.123 declara `filter` dentro de `managedSearchConfiguration` y el
  código lo arma así, pero no se probó ninguna consulta con filtro. Además
  requiere documentos cargados con ese metadato, lo que no está hecho.
- Si los topes de referencia calibrados (10.000 por control, 80.000 en
  total) son adecuados para otras normativas y otros documentos.
- El efecto de la referencia sobre los scripts generados. Las evaluaciones
  grabadas no recorren el camino con la base habilitada.
- La calidad de recuperación real. La evaluación offline usa una fixture
  sintética; las preguntas y los documentos esperados son provisorios hasta
  que exista el conjunto de documentos.
- La forma de `connector_parameters` del conector S3; se tomó del ejemplo del
  proveedor y `validate` solo comprueba el esquema.
- Que los permisos del rol de servicio alcancen para la ingesta.
- El efecto sobre la pila desplegada: se espera una actualización en el lugar
  de las tres Lambdas (una variable de entorno más en el generador), pero no
  se ejecutó `plan`.
- Que Lambda acepte variables de entorno con valor vacío
  (`KNOWLEDGE_BASE_ID`, `KNOWLEDGE_BASE_FORTIOS_VERSION`).
- La integración continua en Linux con el incremento del 2026-11-18.

## 6. Cuota de Bedrock: bloqueo levantado el 2026-11-18

Estado informado el 2026-11-18 (no se consultó AWS al registrarlo): los
pedidos de cuota se cerraron. La cuota aplicada de Claude Sonnet 4.6 para
inferencia entre regiones es de 6.000.000 tokens por minuto y 10 pedidos por
minuto; se habían pedido 10.000 pedidos por minuto. Una llamada mínima a
Converse respondió correctamente. Con 10 pedidos por minuto conviene espaciar
las corridas en vivo.

Lo que sigue es el registro del 2026-11-17 y se conserva como antecedente.

Al 2026-11-17 la cuota aplicada de Claude Sonnet 4.6 en la cuenta del
laboratorio era 0 tokens por minuto y 0 pedidos por minuto (el valor por
defecto de AWS es 6.000.000 y 10.000). Una invocación mínima devolvió
`ThrottlingException: Too many tokens per day`. El código no es la causa: el
cliente envía `maxTokens` explícito y usa reintentos adaptativos.

Ese día se enviaron dos pedidos de aumento por Service Quotas, ambos en
estado pendiente:

| Cuota | Código | Valor pedido |
|---|---|---|
| Tokens por minuto, inferencia entre regiones | `L-15B8E632` | 6.000.000 |
| Pedidos por minuto, inferencia entre regiones | `L-00FF3314` | 10.000 |

Para consultar su estado:

```bash
aws service-quotas list-requested-service-quota-change-history --service-code bedrock --region us-east-1
```

Si son rechazados, el paso siguiente es un caso de soporte de cuenta. Mientras
la cuota sea 0 no se pueden regrabar las evaluaciones en vivo, y por eso la
conexión del RAG al prompt quedó fuera de este incremento.

## 7. Base de conocimientos: fuentes previstas

El conjunto de documentos se definió y se cargó el 2026-11-21; la lista
vigente, con sus fuentes y conversiones, está en el
[manifiesto del corpus](corpus.md). La tabla siguiente es la evaluación
inicial del 2026-11-17 y se conserva como antecedente:

| Fuente | Aporte | Acceso |
|---|---|---|
| Guías de hardening y buenas prácticas de FortiOS | Qué configuración es segura y por qué | Público en docs.fortinet.com |
| Guía de administración y referencia de CLI de FortiOS | Significado de cada parámetro y comando de corrección | Público en docs.fortinet.com |
| CIS Benchmark para FortiGate | Controles con valor esperado y remediación | Gratuito con cuenta CIS, uso no comercial |
| NIST SP 800-53 y NIST CSF | Marco para mapear controles | Público |
| Material propio | Catálogo de endpoints, normativas de la entidad, reportes anteriores | Disponible |
| Referencia oficial de la API REST de FortiOS | Lista completa de endpoints | Solo en la red de desarrolladores de Fortinet (requiere suscripción y aval) |

Condiciones:

- Los documentos de terceros se guardan solo en el bucket privado; no se
  versionan en este repositorio. En el informe se citan como fuentes.
- La documentación debe corresponder a la versión de FortiOS del equipo
  auditado: FortiOS 7.6.8, informada el 2026-11-21.

## 8. Próximos pasos

Hecho el 2026-11-18, en local y sin commit: conexión de los fragmentos al
prompt de generación, registro de fuentes en el manifiesto y en el reporte,
evaluación de recuperación con preguntas y documento esperado, y filtro
opcional por versión de FortiOS en la consulta.

Pendiente (actualizado el 2026-11-21):

1. Revisión del incremento por el desarrollador y decisión de merge.
2. Hecho el 2026-11-21: conjunto de documentos definido, cargado e ingerido
   ([manifiesto](corpus.md)).
3. Ajustar los documentos esperados de las preguntas a las claves reales del
   corpus y grabar la evaluación de recuperación en vivo
   (`--suite retrieval --mode live --record`). La consulta con filtro se
   probó el 2026-11-21 (ver la sección de estado).
4. Regrabar las evaluaciones de generación en vivo, con y sin la base, y
   comparar. La cuota ya no lo impide.
5. Hecho el 2026-11-21 para los tres documentos de Fortinet, que llevan
   `fortios_version`. Falta decidir si el filtro debe habilitarse en el
   pipeline: es una igualdad y deja fuera los documentos sin el atributo.
6. Disparar la ingesta automáticamente al subir un documento.
7. Mostrar las referencias en la aplicación de escritorio y en la API local,
   que hoy las reciben pero no las presentan.

## 9. Otros cambios del mismo día

- El clon local se actualizó a `master` en `32e0ac5`. El estado de Terraform
  y las variables de la pila desplegada estaban en la carpeta anterior
  (`audit-pipeline/terraform/`, ya eliminada del repositorio) y se movieron a
  `infrastructure/pipeline/`. Siguen fuera de Git.
- Se revisó el documento del Proyecto Final de Grado contra el código. La
  revisión de sus capítulos quedó postergada y no forma parte de esta rama.

## 10. Cómo retomar

1. Leer [AGENTS.md](../../../AGENTS.md), este resumen y el handoff.
2. Comprobar rama, último commit y cambios pendientes con Git.
3. Consultar el estado de los pedidos de cuota.
4. Continuar por el primer paso pendiente que no esté bloqueado.
