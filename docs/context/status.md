# Estado documental y pendientes

Síntesis: 2026-11-05; actualizado el 2026-11-21. Fuente principal:
[estado base al 2026-11-04](../base/07-estado-y-pendientes.md), incluida su
actualización WU 5. No se consultó AWS para producir este documento.

## Antecedentes consolidados

| Tema | Último estado de la base | Cómo usarlo |
|---|---|---|
| Despliegue del pipeline | WU 5 informa 42 recursos desplegados en `us-east-1`, cerrando P2 | Antecedente de despliegue; comprobar recursos actuales si la tarea depende de ellos |
| Bedrock | Cuota aplicada 0 y errores de throttling; pendiente P1 | Bloqueo histórico; resuelto según lo informado el 2026-11-18 (ver «Hechos registrados») |
| E2E | WU 5 informa dos pruebas de cableado con fallo Bedrock y sincronización del reporte a API/GUI | No equivale a auditoría exitosa con generación real y FortiGate |
| Catálogo | WU 5 informa ampliación de 11 a 31 endpoints GET; P5 cerrado | Confirmar catálogo vigente antes de ampliarlo |
| Evals | Fixtures manuales ampliadas a 5, 9 y 8 controles por normativa | Grabación live pendiente según la base |
| TLS | WU 5 informa variable Terraform `fortigate_verify_ssl`; P11 cerrado | No repetir como pendiente la descripción anterior del documento de conectividad |
| Correcciones documentales | WU 5 da P12 por aplicado salvo `.env.example` | Revisar archivo actual antes de editar |
| SNS | WU 5 informa suscripción pendiente de confirmación | No asumir entrega de correo actual |
| FortiGate/VPN | La base no registra equipo conectado al pipeline | Verificar conectividad real; el laboratorio es independiente. Para la primera prueba existe la ejecución local (ver «Trabajo que requiere nueva evaluación») |

Las afirmaciones iniciales «infra no desplegada» y «cambios sin commitear» en la
base describen una etapa anterior. No usar P2/P5/P11 como pendientes abiertos.
La rama y el árbol de trabajo actuales se obtienen de Git, no de ese relato.

## Trabajo que requiere nueva evaluación

- Corrida live de las evals y auditoría E2E con evidencia real. La cuota de
  Bedrock dejó de ser un bloqueo el 2026-11-18 (ver más abajo).
- Conectividad FortiGate, perfil GET, token y validación TLS, siguiendo
  [la base de conectividad](../base/06-conexion-fortigate.md).
- **Primera prueba contra un FortiGate real: pendiente.** El equipo disponible
  solo es alcanzable por una VPN de usuario desde una estación Windows, por lo
  que la etapa de ejecución se corre en esa estación con
  `audit-engine/scripts/run_executor_local.py` (2026-11-21), siguiendo
  [la guía de ejecución local](local-executor-run.md). El script está cubierto
  por tests con S3 y FortiGate simulados; no se ejecutó contra AWS ni contra un
  equipo real. La arquitectura objetivo sigue siendo VPN Site-to-Site IPsec con
  el executor en una VPC.
- Confirmación SNS.
- Restricción de egreso del executor, deduplicación e índice de reportes.
- Corpus de evals más amplio: documentos largos, múltiples grupos map y casos
  adversariales. El corpus pequeño no acredita robustez general.
- Revisión de los hallazgos Checkov documentados en
  [checkov-report.md](../../infrastructure/pipeline/checkov-report.md); la base informa
  109 aprobados y 29 fallidos justificados, no ausencia de hallazgos.

- Knowledge Base de Bedrock (2026-11-17 y 2026-11-18): deshabilitada por
  defecto. El generador ya incorpora los fragmentos recuperados a la fase
  reduce y registra las fuentes en el manifest y en el reporte (incremento del
  2026-11-18, sin commit al cierre de esa sesión). Falta definir el corpus,
  comprobar la base real, regrabar las evals en vivo y decidir el merge.
  Detalle en [el handoff](handoffs/2026-11-17-bedrock-knowledge-base.md).

## Hechos registrados

Cada fila indica fecha y fuente. Lo informado en un encargo no fue observado
por el agente que lo registró.

| Fecha | Hecho | Fuente |
|---|---|---|
| 2026-11-15 | CI en Linux aprobado (Ubuntu, Python 3.12): motor con 284 tests aprobados sin omitidos, incluido el backstop SIGALRM real | [Run 43720573002](https://github.com/Santiago-sz/PPS-AWS-Fortinet-/actions/runs/43720573002), registrado en el [handoff de esa tarea](handoffs/2026-11-15-functional-test-readiness.md) |
| 2026-11-18 | Las correcciones de `functional-test-readiness` y la reorganización del repositorio están integradas en `master` | Git: `c314de8` y `ea6e63d` son ancestros de `master` |
| 2026-11-18 | El CI del commit `e86bbc1` de `feature/bedrock-knowledge-base` aprobó sus cinco jobs en Linux | [Run 44227778670](https://github.com/Santiago-sz/PPS-AWS-Fortinet-/actions/runs/44227778670), informado en el encargo; la cantidad de tests aprobados en Linux no fue observada y no se registra |
| 2026-11-18 | Pedidos de cuota de Bedrock cerrados. Cuota aplicada de Claude Sonnet 4.6, inferencia entre regiones: 6.000.000 tokens por minuto y 10 pedidos por minuto (se habían pedido 10.000) | Informado en el encargo; no se consultó AWS |
| 2026-11-18 | Una llamada mínima a Converse respondió correctamente | Informado en el encargo; no se consultó AWS |
| 2026-11-21 | Existe un camino de ejecución local del executor (`scripts/run_executor_local.py`), fuera del paquete de la Lambda. Suite del motor en Windows: 501 aprobados y 1 omitido | Commit `8edc38d` y [handoff](handoffs/2026-11-21-local-executor-runner.md); corrida local, sin AWS ni FortiGate |

Con 10 pedidos por minuto, una corrida live hace pocas llamadas por normativa
(una por grupo de map y hasta tres de reduce), pero varias corridas seguidas o
una normativa larga pueden alcanzar el límite; el cliente usa reintentos
adaptativos.

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
