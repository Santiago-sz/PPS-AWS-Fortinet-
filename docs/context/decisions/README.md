# Índice de decisiones

Primera iteración: 2026-11-05. El registro original se conserva en
[05-decisiones.md](../../base/05-decisiones.md). Los identificadores ADR-01 a
ADR-09 de ese archivo siguen siendo las referencias de origen; no se crean
nuevas decisiones para volver a aprobar las existentes.

| Referencia base | Decisión registrada | Implicación para una tarea |
|---|---|---|
| ADR-01 | Claude mediante Bedrock Converse e IAM | No introducir API keys de Anthropic ni otro transporte por accidente |
| ADR-02 | Dos Lambdas e invocación asíncrona para Fase 1 | Step Functions se considera para necesidades futuras, no está implícitamente autorizado |
| ADR-03 | Remediación propuesta para revisión humana | No aplicar configuración al FortiGate |
| ADR-04 | Clon fuera de Drive; datos Terraform externos | No copiar rutas personales del registro como requisito universal |
| ADR-05 | Executor sin modelo; generador sin secret FortiGate | Mantener separación de roles y responsabilidades |
| ADR-06 | Schedule NIST legacy deshabilitado por defecto | Conservar flujo legacy y comprobar la bandera vigente |
| ADR-07 | Perfil `us.anthropic.claude-sonnet-4-6` | Es la elección documentada; disponibilidad y configuración actuales requieren comprobación |
| ADR-08 | `cachePoint` y máximo de tokens explícito | Comprobar compatibilidad real del SDK; mocks no acreditan soporte del servicio |
| ADR-09 | Gestionar cuota y usar offline mientras falta acceso live | La cuota nula es un antecedente con fecha, no una condición permanente garantizada |

Los detalles de contexto, alternativas y consecuencias están en el registro
base. Este índice sintetiza decisiones; no garantiza que sus argumentos de
seguridad sean propiedades demostradas del código.

## Decisiones posteriores a la base

| Referencia | Decisión registrada | Implicación para una tarea |
|---|---|---|
| [10](10-bedrock-knowledge-base.md) | Knowledge Base administrada de Bedrock en un módulo Terraform aislado; recuperación aditiva y deshabilitada por defecto | No subir el provider del pipeline para esto; no reemplazar el map/reduce completo por fragmentos recuperados |
| [11](11-referencias-en-generacion.md) | Fragmentos recuperados como sección de referencia en reduce: una consulta por control, topes explícitos, fallo blando, trazabilidad en manifest y reporte; idéntico al comportamiento previo con la base deshabilitada | No recuperar con texto de la normativa ni desde el executor; no usar la referencia para ampliar el validador o el catálogo; regrabar evals en vivo antes de evaluar su efecto. Desde el 2026-11-22 cada referencia declara `kind` y el reporte separa las técnicas (`propio/`, `fortinet/`) de las normativas: una carpeta técnica nueva se agrega a `reference_kinds.TECHNICAL_PREFIXES` |
| [12](12-datos-ausentes-indeterminate.md) | El toolkit registra los datos que el script pidió y no obtuvo (endpoint ilegible, tabla que no puede estar vacía, campo ausente) y guarda `indeterminate` en el control afectado, sin cambiar el validador. Implementada el 2026-11-22 en `fix/toolkit-absent-data`; verificada solo con tests, revisión y merge pendientes | No confiar en el estado que informa el script: la garantía es del toolkit. No devolver `None` desde `fgt.get`. Un endpoint nuevo que no pueda estar vacío se agrega a `NEVER_EMPTY_ENDPOINTS`, no a las tuplas de `ENDPOINTS` |
| [13](13-catalogo-de-campos-generador.md) | El generador recibe en el prompt de reduce un catálogo versionado de nombres de campo por endpoint (un equipo, FortiOS 7.6.8) y, dentro del ciclo de reintento existente, avisa cuando un script válido lee un campo no listado, sin rechazarlo. Cada rechazo del validador se registra con su detalle. Implementada el 2026-11-22 en `feature/generator-field-catalog`; verificada solo con tests, sin desplegar ni ejecutar contra un equipo | No convertir el aviso en rechazo ni mover la garantía de la decisión 12 fuera del toolkit. No editar `fortios_field_catalog.py` a mano: se regenera con `scripts/build_field_catalog.py`. Un cambio del catálogo cambia el prompt y pide regrabar las evals en vivo |

## Propuestas pendientes

No son decisiones vigentes. Requieren la aceptación de los autores.

Ninguna al 2026-11-22.

## Nuevas decisiones

Cuando se acepte una decisión duradera que no exista en la base, crear
`<numero>-<tema>.md` aquí y enlazarla desde este índice. Incluir fecha, estado
(propuesta/aceptada/sustituida), problema, opciones, decisión, consecuencias,
fuentes y referencia a la decisión sustituida cuando corresponda. No convertir
una propuesta del agente en decisión aceptada sin respaldo de la tarea.
