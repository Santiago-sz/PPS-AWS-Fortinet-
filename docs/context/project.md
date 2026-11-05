# Proyecto y alcance

Fuente: [arquitectura base](../base/01-arquitectura-fase1.md),
[mapa del repositorio](../base/04-estructura-del-repositorio.md) y
[decisiones base](../base/05-decisiones.md). Síntesis: 2026-11-05.

## Objetivo

Proyecto de tesis/PPS para auditar la postura de seguridad de un FortiGate a
partir de una normativa PDF/DOCX. El sistema extrae controles verificables,
genera un script Python de auditoría, lo valida y ejecuta con capacidades
restringidas. Los hallazgos citan la normativa e incluyen remediaciones propuestas
para revisión humana. El sistema no aplica esas remediaciones al firewall.

La app de escritorio permite cargar normativas y consultar resultados mediante
una API local. El puente de operación a AWS despacha documentos, sincroniza
reportes y permite aprobar ejecuciones pendientes. La GUI no necesita
credenciales AWS; el operador del puente sí necesita la configuración pertinente.

## Mapa para localizar cambios

| Ruta desde la raíz | Responsabilidad |
|---|---|
| `audit-engine/` | Generador, executor, flujo NIST legacy y módulos de extracción, validación, ejecución y reporte |
| `audit-engine/tests/` | Tests del pipeline y de sus contratos |
| `infrastructure/pipeline/` | Infraestructura canónica del pipeline |
| `audit-engine/evals/` | Evaluación offline/live de la generación; normativas sintéticas, expectativas y fixtures |
| `local-api/` | API HTTP local, SQLite y CLI del puente AWS |
| `audit-engine/scripts/` | Construcción del layer de parsers |
| `gui/` | App PySide6, contrato de API y pruebas |
| `infrastructure/fortigate-lab/` | Laboratorio Terraform independiente del despliegue del pipeline |
| `lambda/`, `terraform/` de la raíz | Copias legacy: no editar ni borrar |
| `docs/base/` | Documentación y diagramas originales |
| `docs/context/` | Síntesis de contexto y continuidad de tareas |

## Términos

- **Normativa/policy:** documento de entrada; no confundir con una política IAM
  ni con una regla del firewall.
- **PolicyCheck:** control extraído con identificador, referencia a cláusula,
  endpoints, severidad, intención y propuesta de remediación.
- **Run:** una generación/ejecución identificada por `run_id`.
- **Manifest:** metadatos del run, controles, ubicación del script y hashes.
- **Finding:** resultado por control con evidencia y referencia a la normativa.
- **Harness del modelo:** prompts, validador, sandbox, presupuestos y evals del
  producto, documentados en [la base](../base/03-harness-engineering.md).
- **Harness de desarrollo:** contrato, contexto, skills y hooks para el agente
  que modifica este repositorio; se está definiendo por separado.

## Límites para orientar el trabajo

El acceso al FortiGate es GET sobre un catálogo cerrado. Generador y executor
tienen roles distintos; el executor no accede al modelo y el generador no lee
el token FortiGate. El executor comprueba integridad y repite la validación.
El flujo NIST desplegable se conserva con schedule deshabilitado por defecto.
Las restricciones completas y su autoridad están en [AGENTS.md](../../AGENTS.md).
