# RAG con Amazon Bedrock: resumen de trabajo

Fecha: 2026-11-17; actualizado el 2026-11-18. Rama:
`feature/bedrock-knowledge-base`, creada desde `master` en `32e0ac5`. Estado:
base en los commits `16b45d3` y `e86bbc1`; el incremento del 2026-11-18
(fragmentos en la generación, trazabilidad, filtro y evals de recuperación)
está implementado y verificado en local, sin commit. Revisión y merge
pendientes. Este documento no registra el estado del despliegue en AWS.

Este documento resume lo realizado y sirve como punto de entrada para retomar
el trabajo. El detalle vive en una sola fuente por tema:

| Tema | Fuente de detalle |
|---|---|
| Módulo Terraform, costos, despliegue e ingesta | [README del módulo](../../../infrastructure/knowledge-base/README.md) |
| Decisión de diseño y alternativas descartadas | [Decisión 10](../decisions/10-bedrock-knowledge-base.md) |
| Uso de los fragmentos en la generación y trazabilidad | [Decisión 11](../decisions/11-referencias-en-generacion.md) |
| Evaluación de la calidad de recuperación | [README de evals](../../../audit-engine/evals/README.md) |
| Estado de la tarea, pruebas y pendientes | [Handoff](../handoffs/2026-11-17-bedrock-knowledge-base.md) |
| Contrato de entorno e IAM | [AGENTS.md](../../../AGENTS.md), sección 4 |

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
| Módulo Terraform de la Knowledge Base (bucket de documentos, rol de servicio, base administrada, origen de datos S3) | `infrastructure/knowledge-base/` | Validado con `terraform validate`; no desplegado |
| Enganche en el pipeline (variables, entorno del generador, permiso de consulta condicional; desde el 2026-11-18, `knowledge_base_fortios_version`) | `infrastructure/pipeline/` | Validado; no desplegado |
| Módulo de recuperación, con filtro de metadatos opcional y configuración de búsqueda en una constante | `audit-engine/generator/knowledge_retriever.py` | Con tests |
| Referencia para la generación (2026-11-18): una consulta por control entre map y reduce, topes, sección del prompt y bloque del manifest | `audit-engine/generator/reference_context.py`, `llm_client.py`, `handler_generator.py` | Con tests; sin probar contra una base ni contra el modelo |
| Trazabilidad (2026-11-18): bloque `knowledge_base` en el manifest y `references` por hallazgo en el reporte JSON y Markdown | `contracts/s3_io.py`, `executor/toolkit.py`, `executor/reporter.py` | Con tests |
| Evals de recuperación (2026-11-18): preguntas versionadas, hit rate en k, MRR, umbrales, modos offline y live | `audit-engine/evals/retrieval_eval.py`, `evals/retrieval/` | Offline en verde con fixture **sintética**; live sin ejecutar |
| Tests de contrato entre Terraform y código | `audit-engine/tests/test_knowledge_base_iac.py` | En verde |

Cómo se usa la referencia, en breve (detalle en la decisión 11):

- Después de map, el generador hace una consulta por control con el título y
  la intención de ese control. No usa texto de la normativa como consulta.
- A lo sumo 40 consultas por corrida, 3.000 caracteres de referencia por
  control y 12.000 en total. Un fragmento entra entero o se omite, nunca se
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

Los pasos detallados están en el README del módulo. Ninguno fue ejecutado.

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
- Si los topes de referencia (3.000 por control, 12.000 en total) son
  adecuados; con ellos, un fragmento como el de 9.943 caracteres queda fuera.
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

El conjunto de documentos todavía no está decidido ni cargado. Fuentes
evaluadas:

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
  auditado. Esa versión todavía no fue informada.

## 8. Próximos pasos

Hecho el 2026-11-18, en local y sin commit: conexión de los fragmentos al
prompt de generación, registro de fuentes en el manifiesto y en el reporte,
evaluación de recuperación con preguntas y documento esperado, y filtro
opcional por versión de FortiOS en la consulta.

Pendiente:

1. Revisión del incremento por el desarrollador, commits y decisión de merge.
2. Definir el conjunto de documentos, desplegar el módulo e ingerir.
3. Con la base real: probar una consulta con filtro, ajustar los
   documentos esperados de las preguntas y grabar la evaluación de
   recuperación en vivo (`--suite retrieval --mode live --record`).
4. Regrabar las evaluaciones de generación en vivo, con y sin la base, y
   comparar. La cuota ya no lo impide.
5. Etiquetar los documentos con `fortios_version` (y tipo, si se decide) al
   cargarlos; sin eso el filtro no devuelve resultados.
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
