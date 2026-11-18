# RAG con Amazon Bedrock: resumen de trabajo

Fecha: 2026-11-17. Rama: `feature/bedrock-knowledge-base`, creada desde
`master` en `32e0ac5`. Estado: base implementada y verificada en local; nada
desplegado en AWS; revisión y merge pendientes.

Este documento resume lo realizado y sirve como punto de entrada para retomar
el trabajo. El detalle vive en una sola fuente por tema:

| Tema | Fuente de detalle |
|---|---|
| Módulo Terraform, costos, despliegue e ingesta | [README del módulo](../../../infrastructure/knowledge-base/README.md) |
| Decisión de diseño y alternativas descartadas | [Decisión 10](../decisions/10-bedrock-knowledge-base.md) |
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
| Enganche en el pipeline (variables, entorno del generador, permiso de consulta condicional) | `infrastructure/pipeline/` | Validado; no desplegado |
| Módulo de recuperación | `audit-engine/generator/knowledge_retriever.py` | Con tests; todavía no conectado al prompt |
| Tests de contrato entre Terraform y código | `audit-engine/tests/test_knowledge_base_iac.py` | En verde |

Reglas que se mantienen:

- El RAG está **apagado por defecto**: con `knowledge_base_id` vacío el
  pipeline se comporta igual que antes y el rol del generador no recibe
  ningún permiso sobre Knowledge Bases.
- El permiso `bedrock:Retrieve` es una política aparte, existe solo cuando la
  variable tiene valor y apunta al ARN exacto de esa base.
- El ejecutor y el evaluador heredado no reciben permisos de Bedrock.
- No se modificaron prompts, validador, sandbox ni el flujo heredado.

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

## 5. Qué no está verificado

Nada se probó contra una Knowledge Base real. Queda por confirmar al
desplegar:

- La configuración de búsqueda que requiere una base administrada en
  `Retrieve` (`vectorSearchConfiguration` o `managedSearchConfiguration`). La
  petición se arma en una sola función.
- La forma de `connector_parameters` del conector S3; se tomó del ejemplo del
  proveedor y `validate` solo comprueba el esquema.
- Que los permisos del rol de servicio alcancen para la ingesta.
- El efecto sobre la pila desplegada: se espera una actualización en el lugar
  de las tres Lambdas, pero no se ejecutó `plan`.
- La ejecución de la integración continua en Linux con estos cambios.

## 6. Bloqueo vigente: cuota de Bedrock

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

1. Conectar los fragmentos recuperados al prompt de generación del script y
   regrabar las evaluaciones en vivo (bloqueado por la cuota).
2. Registrar en el manifiesto y en el reporte qué fragmento y qué documento
   respaldó cada control.
3. Agregar a las evaluaciones un conjunto de preguntas con el documento
   esperado, para medir la calidad de la recuperación.
4. Etiquetar los documentos con versión de FortiOS y tipo, y filtrar por esos
   metadatos al consultar.
5. Disparar la ingesta automáticamente al subir un documento.
6. Definir el conjunto de documentos, desplegar el módulo e ingerir.

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
