# Estado documental y pendientes

Síntesis: 2026-11-05; actualizado el 2026-11-21. Fuente principal:
[estado base al 2026-11-04](../base/07-estado-y-pendientes.md), incluida su
actualización WU 5. No se consultó AWS para producir este documento, salvo
las filas de «Hechos registrados» que lo indican.

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
- **Primera prueba contra un FortiGate real: realizada el 2026-11-21, con
  resultados a revisar.** El equipo solo es alcanzable por una VPN de usuario
  desde una estación Windows, por lo que la etapa de ejecución se corrió en esa
  estación con `audit-engine/scripts/run_executor_local.py`, siguiendo
  [la guía de ejecución local](local-executor-run.md). La corrida
  `9c1fa81e1a154d1fa510274997381280` (normativa DA 641/2021) terminó en
  `completed` con 12 hallazgos: 8 `pass` y 4 `fail`. El reporte quedó solo en
  disco local (`audit-engine/local-runs/`, ignorado por git) porque contiene
  configuración real del equipo. El mismo día se adjuntó con `import-result` a
  una auditoría de la API local y se comprobó que la aplicación de escritorio
  lo muestra, sin cambios de código ni escrituras en AWS
  ([pasos](local-executor-run.md#9-ver-el-reporte-local-en-la-aplicación-de-escritorio)).
- **Calidad de los hallazgos de esa corrida: pendiente de corrección.** La
  lectura del reporte muestra controles cuyo resultado no está respaldado por
  la evidencia:
  - Dos controles sobre administradores aprobaron con cero administradores y
    cero usuarios de API leídos, cuando el equipo tiene al menos el usuario de
    API usado en la prueba. Un dato vacío debería dar `indeterminate`, no
    `pass`. Falta determinar si el perfil de solo lectura no alcanza ese
    endpoint o si el script interpreta mal la respuesta.
  - Un control de registro falló con los campos de evidencia vacíos (nombres de
    campo que el equipo no devolvió); debería dar `indeterminate`.
  - El control de NTP falló por no tener servidores propios aunque el equipo
    sincroniza con FortiGuard.
  - Antivirus e IPS tienen la misma cobertura (3 de 11 políticas activas) y uno
    aprobó y el otro falló: el criterio no es uniforme.
  - Una remediación propone una longitud mínima de contraseña menor que la ya
    configurada, porque se genera sin conocer la configuración leída.
- La arquitectura objetivo sigue siendo VPN Site-to-Site IPsec con el executor
  en una VPC.
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
  2026-11-18). Desplegada el 2026-11-18. El 2026-11-21 se cargó el corpus
  definitivo (25 documentos: Fortinet 7.6, NIST, STIG de DISA y normativa de
  Argentina y España) y una ingesta nueva dejó el índice sincronizado con el
  bucket, sin fallos y sin las normativas de ejemplo retiradas. Ese mismo día
  se retiró la guía de FortiOS 8.0.0, que no corresponde al equipo auditado
  (7.6.8), con lo que el corpus queda en 24 documentos. Falta ajustar y grabar
  la evaluación de recuperación en vivo, regrabar las evals de generación y
  decidir el merge. Detalle en [el resumen del RAG](rag/README.md), el
  [manifiesto del corpus](rag/corpus.md) y
  [el handoff](handoffs/2026-11-17-bedrock-knowledge-base.md).

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
| 2026-11-21 | Corpus de la Knowledge Base cargado: 25 documentos, 24,45 MB. Ingesta `R4MQ9D7QQZ` en `COMPLETE`: 25 examinados, 23 nuevos indexados, 3 quitados del índice, 0 fallidos. Consultas `Retrieve` devuelven los documentos nuevos y ya no las normativas de ejemplo retiradas. Suite del motor en Windows: 522 aprobados y 1 omitido | Observado en AWS en esa sesión (`get-ingestion-job`, `list-knowledge-base-documents`, `retrieve`), con autorización del dueño para escribir en el bucket de conocimiento e iniciar la ingesta; [resumen del RAG](rag/README.md) y [manifiesto](rag/corpus.md) |

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
