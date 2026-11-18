# 11 — Documentación de referencia en la generación del script

- Fecha: 2026-11-18.
- Estado: los requisitos (puntos 1 a 6) vienen del encargo de la tarea
  `bedrock-knowledge-base`; los valores y formatos concretos (topes, texto de
  la nota, forma del bloque) son propuesta de la implementación, pendientes
  de revisión del desarrollador.
- Complementa la [decisión 10](10-bedrock-knowledge-base.md), cuyo punto 5
  dejaba este paso para un incremento posterior. No sustituye ninguna.

## Problema

Usar los fragmentos recuperados de la Knowledge Base para mejorar el script
generado sin cambiar nada cuando la base está deshabilitada, sin debilitar el
validador ni el sandbox, sin recortar la normativa y dejando registro de qué
documento respaldó cada control.

## Opciones consideradas

| Opción | Resultado |
|---|---|
| Recuperar con el texto de cada chunk de la normativa, antes de map | Descartada: envía texto de la normativa como consulta, multiplica llamadas y mezcla referencia con extracción de controles |
| Una consulta única con todos los controles | Descartada: la recuperación devuelve lo más parecido al conjunto, no a cada control, y no permite trazabilidad por control |
| Recuperar en el executor para enriquecer el reporte | Descartada: el executor no tiene acceso a Bedrock (regla 4 de `AGENTS.md`) |
| Una consulta por control, entre map y reduce, con sección delimitada en el prompt de reduce | **Elegida** |

## Decisión

1. **Deshabilitado es idéntico.** Con `KNOWLEDGE_BASE_ID` vacío o ausente el
   generador no lee ninguna otra variable de la base, llama a `llm_client`
   con los mismos argumentos y produce los mismos prompts, manifest y reporte.
   Lo fijan tests con hashes calculados sobre el commit `e86bbc1`. En
   consecuencia, **un manifest sin el bloque `knowledge_base` significa
   recuperación deshabilitada**; el bloque solo existe cuando estuvo
   habilitada.
2. **Dónde y con qué.** `reference_context.collect` se ejecuta una vez,
   después de map y antes de reduce. Hace una consulta por control armada con
   `title` e `intent` del control; nunca con chunks ni con la cita de
   `clause_ref`.
3. **Topes.** `MAX_RETRIEVE_CALLS = 40` llamadas por corrida,
   `MAX_REFERENCE_CHARS_PER_CONTROL = 3000` caracteres de referencia por
   control y `MAX_REFERENCE_CHARS = 12000` en total. **Un fragmento de
   referencia entra entero o se omite; nunca se recorta**, porque un corte
   puede dejar a medias un bloque de configuración y volverlo engañoso. Por
   control se recorren los resultados en el orden del servicio: el que no
   cabe en lo que queda del presupuesto se omite y se prueba el siguiente.
   Sobre el total se descartan primero los de menor puntaje. Nunca se recorta
   la normativa ni se quita un control. Consecuencia aceptada: un fragmento
   mayor que el presupuesto por control queda siempre fuera, aunque sea el de
   mayor puntaje (el 2026-11-18 se observó uno de 9.943 caracteres junto a
   otros de 1.463, 1.109 y 1.082). No se asume que el servicio devuelva la
   cantidad pedida: pedir 3 devolvió 2.
4. **Cómo entra al prompt.** Sección delimitada en el prompt de usuario de
   reduce, agrupada por `check_id`, cada fragmento con su fuente y puntaje. El
   system prompt de reduce suma una nota, solo con la recuperación habilitada,
   que la declara material de consulta y no instrucciones, y que no amplía lo
   que el script puede llamar. El texto recuperado no puede cerrar la sección:
   los delimitadores que aparezcan dentro se neutralizan. El control efectivo
   sigue siendo `script_validator` y el catálogo de endpoints, sin cambios.
5. **Fallo blando y visible.** Un error de recuperación deja a ese control
   sin referencia y la generación continúa. Se emite `kb_retrieve` por
   consulta fallida y `kb_references` con el resumen. El bloque del manifest
   informa controles con referencia, consultas fallidas, controles omitidos
   por el tope de llamadas y fragmentos descartados por el tope de tamaño.
6. **Trazabilidad.** El bloque `knowledge_base` del manifest guarda, por
   `check_id`, fuente y puntaje de cada fragmento usado, nunca su texto. La
   fuente es **la clave del objeto** (por ejemplo
   `fortinet/FortiOS-8.0.0-Best_Practices.pdf`), no el URI: el servicio
   devuelve `https://<bucket>.s3.amazonaws.com/<clave>` y el nombre del bucket
   incluye el id de cuenta. `knowledge_retriever.source_identifier` hace esa
   reducción antes de que el origen llegue al prompt, al manifest, a los
   eventos o a las fixtures de evals. El
   executor no consulta nada: `toolkit.ReportCapability` lee ese bloque y
   agrega `references` a cada hallazgo, igual que `clause_ref`; el script no
   puede pasarlas. El reporte las muestra en JSON y en una sección Markdown.
7. **Filtro opcional.** `KNOWLEDGE_BASE_FORTIOS_VERSION` agrega un filtro
   `equals` sobre el metadato `fortios_version`. Vacío significa sin filtro.
8. **Configuración de búsqueda.** La petición se arma solo en
   `knowledge_retriever.build_request` y la configuración usada es la
   constante `SEARCH_CONFIGURATION_KEY`, con valor
   `managedSearchConfiguration`. Comprobado contra la base desplegada el
   2026-11-18 (informado por quien hizo la prueba; este cambio no llamó a
   AWS): con `vectorSearchConfiguration` el servicio responde
   `ValidationException: Incompatible configuration: vectorSearchConfiguration
   is not supported for managed knowledge bases. Use managedSearchConfiguration
   instead.`; con `{"managedSearchConfiguration": {"numberOfResults": 3}}` la
   consulta funciona.

## Consecuencias

- Con la recuperación habilitada cambian los prompts de reduce: las fixtures
  grabadas de las evals no representan ese camino. Hay que grabar una corrida
  live con la base real antes de afirmar algo sobre su efecto.
- El reporte y el manifest identifican cada documento por su clave dentro
  del bucket, sin el bucket. Dos buckets con la misma clave no se distinguen;
  hoy hay un solo bucket de documentos.
- El executor confía en que el manifest ya trae claves: no puede importar el
  módulo de recuperación para volver a reducirlas.
- Un valor inválido de `KNOWLEDGE_BASE_MAX_RESULTS` con la base habilitada
  hace fallar la invocación de forma explícita, no se corrige en silencio.
- `local-api` y `gui` no validan de forma estricta las claves del manifest ni
  del reporte, por lo que los campos nuevos no los afectan; tampoco los
  muestran todavía.
- El filtro solo funciona si los documentos se cargan con el metadato
  `fortios_version`; ese etiquetado no está hecho.

## Sin verificar

- El código de este incremento no se ejecutó contra la Knowledge Base real
  ni contra el modelo. Lo comprobado contra el servicio son la configuración
  de búsqueda y la forma de los resultados (punto 8 y punto 6).
- **El filtro de metadatos dentro de `managedSearchConfiguration`.** El
  modelo de servicio de botocore 1.43.123 lo declara
  (`ManagedSearchConfiguration.filter`, de tipo `RetrievalFilter`, igual que
  en la configuración vectorial), y el código lo arma en esa forma, pero no
  se probó ninguna consulta con filtro contra el servicio.
- Si los topes por control y total son adecuados: los tamaños observados
  corresponden a una sola consulta.
- No se midió si la referencia mejora o empeora los scripts generados.

## Fuentes

- Modelo de servicio de botocore 1.43.123, `bedrock-agent-runtime`:
  `RetrieveRequest`, `KnowledgeBaseRetrievalConfiguration`,
  `KnowledgeBaseVectorSearchConfiguration`, `ManagedSearchConfiguration`,
  `RetrievalFilter`, `FilterAttribute`.
- [Handoff de la tarea](../handoffs/2026-11-17-bedrock-knowledge-base.md) y
  [resumen de RAG](../rag/README.md).
