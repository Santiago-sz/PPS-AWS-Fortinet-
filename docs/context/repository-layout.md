# Arquitectura del repositorio

Implementación: 2026-11-05. Estructura acordada durante la conversación y aplicada
sin despliegues ni cambios del comportamiento del motor de auditoría.

```text
gui/                         Aplicación PySide6 y cliente HTTP/HTTPS
local-api/                   Servidor local y operación explícita del puente AWS
audit-engine/
  generator/                 Extracción, chunking, prompts y Bedrock
  executor/                  Ejecución, capacidades, lecturas FortiGate y reportes
  contracts/                 Validador AST, artefactos, observabilidad y secrets
  legacy/                    Handlers NIST conservados sin modificación
  tests/                     Suite del motor y contratos IaC/código
  evals/                     Evaluación de generación offline/live
  scripts/                   Construcción del layer
infrastructure/
  pipeline/                  Terraform canónico del pipeline
  fortigate-lab/             Laboratorio independiente
docs/base/                   Documentación original conservada como antecedente
docs/context/                Conocimiento actualizado y handoffs
lambda/, terraform/          Copias legacy de raíz: intactas
```

## API local

`server/` se comunica con `services/`, que utiliza `domain/` y `storage/`.
El paquete `aws/` contiene el puente, la configuración de credenciales y el
despacho de comandos CLI. No se importa desde el servidor. El SDK se carga solo
al ejecutar operaciones AWS. El formato SQLite y la sintaxis `serve`,
`import-result` y `aws dispatch|sync|list-pending|approve` se mantienen.

HTTPS es configurable por certificado/clave PEM. La GUI permite confiar en una
CA local sin desactivar validación TLS. Se mantiene HTTP loopback para desarrollo
compatible. Ver [manual API](../../local-api/README.md).

## Empaquetado e infraestructura

Los módulos del motor conservan los imports planos. Pytest y evals añaden las
cuatro áreas al path; Terraform empaqueta sus archivos Python en la raíz del ZIP
mediante bloques `source`. Los nombres de los handlers y recursos Terraform no
cambian. No se incluyen tests ni bytecode en ese archivo.

La separación de carpetas no constituye aislamiento de permisos. Los roles IAM
siguen definiendo las capacidades del generador y executor. Este cambio conserva
el ZIP común existente y la revalidación independiente del executor.

El layer se construye en `audit-engine/layers/`. Ejecutar Terraform desde
`infrastructure/pipeline/`; `init -backend=false` y `validate` utilizan
`TF_DATA_DIR` fuera del repositorio. No mover estados de Terraform entre entornos
ni ejecutar plan/apply por interpretar esta migración como un despliegue.

## Rutas anteriores

| Antes | Ahora |
|---|---|
| `desktop/` | `gui/` |
| `audit-pipeline/api/` | `local-api/` |
| `audit-pipeline/lambda/` | Áreas de `audit-engine/` |
| `audit-pipeline/lambda/tests/` | `audit-engine/tests/` |
| `audit-pipeline/evals/` y `scripts/` | `audit-engine/evals/` y `scripts/` |
| `audit-pipeline/terraform/` | `infrastructure/pipeline/` |
| `fortigate-sandbox-2026-06-07/` | `infrastructure/fortigate-lab/` |

La documentación base describe las rutas originales. Los comandos de los manuales
activos, CI y `AGENTS.md` se actualizan a estas ubicaciones. Reinstalar paquetes
editables con `pip install -e "local-api[dev]" -e "gui[dev]"` si el entorno apuntaba
a las ubicaciones anteriores. Los nombres de paquetes y comandos instalados no
cambian (`pps_api`, `pps_desktop`, `pps-api`, `pps-desktop`).
