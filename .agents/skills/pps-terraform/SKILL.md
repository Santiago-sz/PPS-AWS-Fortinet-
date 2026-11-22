---
name: pps-terraform
description: "Modificar o revisar Terraform del pipeline o laboratorio PPS en infrastructure/. Usar para IAM, recursos, variables, red y empaquetado; no presupone autorización para plan/apply o cambios AWS."
---

# Infraestructura PPS

Consultar [AGENTS.md](../../../AGENTS.md),
[TESTING.md](../../../audit-engine/TESTING.md),
[SECRETS.md](../../../audit-engine/SECRETS.md) y el módulo afectado.

1. Distinguir `infrastructure/pipeline/`, `infrastructure/knowledge-base/`
   (provider aws 6.x y estado propios) e `infrastructure/fortigate-lab/`.
   No trabajar sobre `terraform/` legacy de raíz ni mezclar estados de módulos.
2. Definir primero cómo verificar el cambio: test de contrato IaC/código para
   variables/handlers, o formato y validación para cambios puramente declarativos.
   Escribir y observar el fallo de los tests nuevos antes de implementar.
3. Mantener nombres/direcciones de recursos salvo requerimiento de migración
   explícito. Revisar efectos de reemplazo potenciales sin ejecutar un plan.
   No mezclar rol generador con lectura de secrets ni executor con Bedrock.
4. Comprobar rutas de ZIP/layer desde `path.module`; construir el layer cuando
   `filebase64sha256` lo requiera. Conservar credenciales y estados fuera de Git.
5. Ejecutar `fmt -check -recursive`, `init -backend=false -input=false` y
   `validate` usando `TF_DATA_DIR` fuera del árbol. Ejecutar Checkov y comparar
   con [el informe](../../../infrastructure/pipeline/checkov-report.md).

Registrar hallazgos preexistentes y nuevos por separado; actualizar el informe
si cambia el resultado. Una validación sintáctica o checks con excepciones no
demuestran un despliegue correcto. No ejecutar plan/apply ni AWS mutante sin
pedido explícito. Una skill no autoriza esas operaciones.
