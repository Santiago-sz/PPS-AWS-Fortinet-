# Estado documental y pendientes

Síntesis: 2026-11-05. Fuente principal:
[estado base al 2026-11-04](../base/07-estado-y-pendientes.md), incluida su
actualización WU 5. No se consultó AWS para producir este documento.

## Antecedentes consolidados

| Tema | Último estado de la base | Cómo usarlo |
|---|---|---|
| Despliegue del pipeline | WU 5 informa 42 recursos desplegados en `us-east-1`, cerrando P2 | Antecedente de despliegue; comprobar recursos actuales si la tarea depende de ellos |
| Bedrock | Cuota aplicada 0 y errores de throttling; pendiente P1 | Bloqueo histórico, pendiente de nueva comprobación |
| E2E | WU 5 informa dos pruebas de cableado con fallo Bedrock y sincronización del reporte a API/GUI | No equivale a auditoría exitosa con generación real y FortiGate |
| Catálogo | WU 5 informa ampliación de 11 a 31 endpoints GET; P5 cerrado | Confirmar catálogo vigente antes de ampliarlo |
| Evals | Fixtures manuales ampliadas a 5, 9 y 8 controles por normativa | Grabación live pendiente según la base |
| TLS | WU 5 informa variable Terraform `fortigate_verify_ssl`; P11 cerrado | No repetir como pendiente la descripción anterior del documento de conectividad |
| Correcciones documentales | WU 5 da P12 por aplicado salvo `.env.example` | Revisar archivo actual antes de editar |
| SNS | WU 5 informa suscripción pendiente de confirmación | No asumir entrega de correo actual |
| FortiGate/VPN | La base no registra equipo conectado al pipeline | Verificar conectividad real; el laboratorio es independiente |

Las afirmaciones iniciales «infra no desplegada» y «cambios sin commitear» en la
base describen una etapa anterior. No usar P2/P5/P11 como pendientes abiertos.
La rama y el árbol de trabajo actuales se obtienen de Git, no de ese relato.

## Trabajo que requiere nueva evaluación

- Cuota Bedrock, corrida live y auditoría E2E con evidencia real.
- Conectividad FortiGate, perfil GET, token y validación TLS, siguiendo
  [la base de conectividad](../base/06-conexion-fortigate.md).
- Confirmación SNS, resultados efectivos de CI y prueba SIGALRM en Linux.
- Restricción de egreso del executor, deduplicación e índice de reportes.
- Corpus de evals más amplio: documentos largos, múltiples grupos map y casos
  adversariales. El corpus pequeño no acredita robustez general.
- Revisión de los hallazgos Checkov documentados en
  [checkov-report.md](../../infrastructure/pipeline/checkov-report.md); la base informa
  109 aprobados y 29 fallidos justificados, no ausencia de hallazgos.

Las referencias a recursos, versiones y cuotas son históricas. Esta lista no
autoriza despliegues, cambios IAM, modificaciones del firewall ni costos live.

## Definición del harness de desarrollo

Acuerdos de la conversación, aún sin implementar en `AGENTS.md` ni en hooks:

- Definir reglas, fuentes de contexto, selección de skills y uso de hooks.
- Aplicar tests primero para comportamiento ejecutable.
- Mantener handoffs en `docs/context/handoffs/` antes de perder continuidad.
- Primera entrega autorizada: trasladar la documentación previa a `docs/base/`
  y generar este contexto a partir de ella.
- La compatibilidad inicial de agentes, las skills concretas y la política de
  hooks todavía deben acordarse. No hay hooks nuevos activados por esta tarea.
