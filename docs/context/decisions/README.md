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

## Nuevas decisiones

Cuando se acepte una decisión duradera que no exista en la base, crear
`<numero>-<tema>.md` aquí y enlazarla desde este índice. Incluir fecha, estado
(propuesta/aceptada/sustituida), problema, opciones, decisión, consecuencias,
fuentes y referencia a la decisión sustituida cuando corresponda. No convertir
una propuesta del agente en decisión aceptada sin respaldo de la tarea.
