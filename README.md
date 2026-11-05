# PPS-AWS-Fortinet — auditoría de FortiGate guiada por normativas

Sistema que convierte una **normativa de seguridad (PDF/DOCX)** en una
**auditoría automática y de solo lectura** de un firewall FortiGate, con
hallazgos que citan la cláusula incumplida y remediaciones propuestas para
revisión humana. Proyecto de tesis / PPS; infraestructura en AWS.

## Arquitectura en un párrafo

Subir la normativa a `s3://<policies-bucket>/policies/` dispara la Lambda
`policy_generator`: extrae el texto, lo divide en chunks que respetan los
límites de cláusula y, con Claude vía **Amazon Bedrock**, hace un *map*
(cláusulas → controles verificables contra un catálogo cerrado de endpoints
FortiGate) y un *reduce* (controles → script Python). El script pasa por un
**validador AST de allowlist** (sin imports, sin escritura, sin reflexión;
reintenta con feedback hasta 3 veces) y se firma con SHA-256. La Lambda
`audit_executor` —sin acceso al modelo— re-valida el script, lo ejecuta en
un **sandbox** con presupuestos duros que solo expone `fgt.get()` y
`report.finding()`, consulta la REST API del FortiGate y publica
`report.md`/`report.json` en S3 y una notificación SNS. La app de
escritorio (`gui/`) y la API local (`local-api`) permiten
subir normativas, aprobar ejecuciones y revisar reportes sin credenciales
AWS. El sistema **nunca modifica el FortiGate**.

## Empezar

- Organización del código: [`docs/context/repository-layout.md`](docs/context/repository-layout.md).
  Componentes independientes en `gui/`, `local-api/`, `audit-engine/` e
  `infrastructure/`. El servidor local y el puente AWS tienen módulos separados;
  la API y la GUI admiten HTTPS local con verificación de certificados.

- Operación y despliegue: [`docs/README.md`](docs/README.md) (índice de la
  documentación: arquitectura, paso a paso de despliegue y prueba, harness,
  conexión al FortiGate, estado y pendientes), complementado por
  `audit-engine/TESTING.md`, `audit-engine/SECRETS.md`,
  `infrastructure/pipeline/terraform.tfvars.example` y el output
  `next_steps` del `terraform apply`.
- Reglas para agentes y colaboradores, mapa de carpetas y definición de
  terminado: [`AGENTS.md`](AGENTS.md).
- Evaluación de la calidad del generador: `audit-engine/evals/README.md`.
- App de escritorio: `gui/` (`SPEC_GUI_PPS_AWS_FORTINET.md` describe la
  especificación de la GUI).

Las carpetas `lambda/` y `terraform/` de la raíz son copias legacy
obsoletas; el código canónico vive en `audit-engine/`.
