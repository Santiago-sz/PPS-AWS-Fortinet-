# Estado documental y pendientes

Síntesis: 2026-11-05; actualizado el 2026-11-22. Fuente principal:
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
- **Segunda corrida real, con la base de conocimientos actualizada
  (2026-11-21/22).** Misma normativa y mismo equipo; cambia solo el corpus
  (24 documentos, ver [manifiesto](rag/corpus.md)). Generación
  `dd1b2879454a4ddfb426c395481312c0`: 14 controles, los 14 con referencias de
  la base, script válido al segundo intento (el primero fue rechazado por la
  lista de permitidos). Ejecución local: `completed`, 14 hallazgos, 7 `pass` y
  7 `fail` (la primera corrida dio 12 hallazgos, 8 `pass` y 4 `fail`). Como
  `AUTO_EXECUTE` está activo, el executor de AWS también corrió y dejó en S3 un
  reporte sin datos, porque no alcanza el equipo; el resultado válido es el
  local. Comparación con la primera corrida:
  - Mejoró: antivirus, monitoreo continuo (IPS) y filtrado web fallan con el
    mismo criterio para la misma cobertura (3 de 11 políticas); hay dos
    controles nuevos (gestión de cuentas y filtrado web); las referencias
    citan 13 documentos distintos contra 6 en la primera corrida.
  - Mejora solo aparente, verificada leyendo los scripts generados: el control
    de registro de actividad de administradores muestra `disable` en lugar de
    campos vacíos, pero el script asigna ese valor cuando el campo no viene en
    la respuesta, así que no es un valor leído; el control de gestión de
    vulnerabilidades falla por campos de FortiGuard que también toman un valor
    por defecto; la remediación que propone una longitud mínima de contraseña
    menor que la configurada sigue en el manifest y solo queda oculta porque
    el control ahora aprueba.
  - Causa común que surge de esa lectura: los scripts tratan un campo ausente
    como un valor (`disable`, cero, lista vacía) en lugar de marcar el control
    como `indeterminate`. Es el mismo defecto que hace aprobar los controles
    de administradores con cero administradores leídos.
  - Sigue igual: los dos controles de administradores leen cero
    administradores y aprueban (el perfil del usuario de API es
    `super_admin_readonly`, por lo que la causa está en el script o en el
    manejo de la respuesta, no en los permisos); el control de NTP falla aunque
    el equipo sincroniza con FortiGuard.
  - Criterios discutibles nuevos: el control de gestión de cuentas falla por
    la existencia de una cuenta local deshabilitada; el de protección de las
    comunicaciones aprueba con la misma cobertura baja de inspección SSL que
    hace fallar al antivirus; el control de contraseñas cambió de criterio
    entre corridas.
  - Límite de la comparación: la generación con un modelo de lenguaje no es
    determinista y hay una sola corrida por lado, por lo que las diferencias
    no pueden atribuirse por completo al corpus. Es evidencia de mejora, no una
    medición; para medir hacen falta varias corridas por lado.
  - Ambas corridas quedaron asociadas a auditorías locales de la aplicación
    para verlas lado a lado; los reportes no se versionan.
- **Diagnóstico de la forma de las respuestas (2026-11-22): implementado y
  ejecutado contra un equipo de laboratorio; pendiente contra el equipo
  institucional.**
  `audit-engine/scripts/diagnose_fortigate_local.py` repite el `GET` del
  pipeline para cada endpoint del catálogo e informa solo la estructura de la
  respuesta (código HTTP, tipo de `results`, cantidad de elementos y nombres de
  campo), sin valores del equipo, sin host y sin token. Debe ejecutarse antes
  de cambiar el toolkit, para saber qué devuelven `system/admin`,
  `system/api-user`, `system/accprofile`, los endpoints de registro,
  `system/ntp` y `system/fortiguard`. Pasos en
  [la guía](local-executor-run.md#10-diagnóstico-de-la-forma-de-las-respuestas).
  Actualización del mismo día: el diagnóstico se ejecutó contra un equipo de
  laboratorio (ver el punto siguiente).
- **Corrección del falso `pass` por datos ausentes (2026-11-22): implementada
  y verificada solo con tests; no se volvió a ejecutar contra un equipo.**
  Rama `fix/toolkit-absent-data`, sin merge. El diagnóstico, ejecutado con
  `--probe-global-scope` contra un equipo de laboratorio con FortiOS 7.6.8 y
  un usuario de API con perfil `super_admin_readonly`, mostró (informado en el
  encargo): `system/admin` y `system/api-user` responden HTTP 200 con lista
  vacía aunque el equipo tiene al menos cuatro administradores y el propio
  usuario de API; `vpn.ipsec/phase1-interface` y `user/radius` responden lista
  vacía y están realmente vacías; `system/dhcp/server` y `system/snmp/sysinfo`
  responden HTTP 400. Los controles generados informaban `total_admins=0` con
  estado `pass`. Con el cambio, el toolkit guarda `indeterminate` cuando el
  control depende de un endpoint ilegible, de una tabla que no puede estar
  vacía o de un campo que la respuesta no trae, y conserva el estado
  informado, las lagunas y el motivo; un `fail` afectado también pasa a
  `indeterminate`. Las dos rutas con HTTP 400 se corrigieron a
  `system.dhcp/server` y `system.snmp/sysinfo`. Detalle, diferencias con el
  diseño y pendientes en la
  [decisión 12](decisions/12-datos-ausentes-indeterminate.md#implementación-2026-11-22)
  y en [el handoff](handoffs/2026-11-22-toolkit-absent-data.md).
  - Pregunta abierta: por qué un usuario de API `super_admin_readonly` recibe
    vacía la tabla de administradores. Que el perfil limite la visibilidad es
    una hipótesis sin verificar; falta repetir la lectura con otro perfil. La
    afirmación anterior de este documento («la causa está en el script o en el
    manejo de la respuesta, no en los permisos») queda sin respaldo: el equipo
    responde la lista vacía.
  - No resuelto por este cambio: criterios incorrectos sobre datos leídos
    (NTP, cobertura de antivirus e IPS) y nombres de campo que el modelo
    inventa. El prompt del generador no se modificó.
- **Catálogo de campos para el generador (2026-11-22): implementado y
  verificado solo con tests; sin desplegar, sin invocar al modelo y sin
  ejecutar contra un equipo.** Rama `feature/generator-field-catalog`, sin
  merge. Motivo (informado en el encargo): en dos corridas contra el
  laboratorio, entre 4 y 8 de 14 a 17 controles terminaron en `indeterminate`
  porque el script pidió campos que la respuesta no trae (`ssl-min-proto-ver`,
  `admin`, `event`, `status`, `update-schedule`, `update-schedule-frequency`,
  `zone`). Con el cambio, el prompt de reduce lleva un catálogo de nombres de
  campo por endpoint construido a partir de dos diagnósticos del laboratorio
  (FortiOS 7.6.8; 27 endpoints observados y 4 sin verificar), y un script
  válido que lee un campo no listado recibe una pista de corrección dentro del
  ciclo de reintento, sin ser rechazado. El system prompt de reduce pasa de
  3.336 a 39.583 caracteres (estimado: 9.000 a 10.500 tokens más por llamada).
  Cada rechazo del validador se registra ahora con regla, línea y mensaje.
  Detalle y límites en la
  [decisión 13](decisions/13-catalogo-de-campos-generador.md) y en
  [el handoff](handoffs/2026-11-22-generator-field-catalog.md).
  - Las fixtures grabadas de evals son anteriores al catálogo. El modo offline
    sigue saliendo con código 0, pero informa 6 campos no listados en los tres
    scripts grabados y 3 llamadas de corrección sin respuesta grabada. Falta
    regrabar en vivo.
  - No medido: si el modelo respeta la lista y cuánto bajan los
    `indeterminate`. `dhcp_servers`, `snmp_sysinfo`, `vpn_ipsec` y
    `radius_servers` no tienen campos en el catálogo.
  - En la misma rama: el manifest marca cada referencia de la base de
    conocimientos como técnica (`propio/`, `fortinet/`) o normativa, y el
    reporte lista las técnicas bajo «Referencias técnicas (no normativas)».
    La recuperación no cambió. Detalle en la
    [decisión 11](decisions/11-referencias-en-generacion.md#actualización-del-2026-11-22-referencias-técnicas-y-normativas).
- **Demostración de la tesis (decisión de los dos autores, 2026-11-22):** se
  hará con un FortiGate de laboratorio dentro de AWS, no con el equipo
  institucional, para que la Lambda ejecutora alcance el equipo y todo el flujo
  corra en AWS. El laboratorio no está construido; `infrastructure/fortigate-lab`
  apunta a `sa-east-1` y el pipeline está en `us-east-1`. Qué hay que decidir y
  hacer está en
  [la guía de puesta en marcha](puesta-en-marcha-desde-cero.md#9-estado-actual-defectos-conocidos-y-próximos-pasos).
  La ejecución local por VPN sigue documentada, pero ya no es el camino de la
  demostración.
- **Laboratorio FortiGate en AWS (2026-11-22): Terraform reescrito, sin
  aplicar.** `infrastructure/fortigate-lab` ahora define, en `us-east-1` y para
  una cuenta separada, una VPC con subredes `wan`, `lan` y `dmz`, un
  FortiGate-VM bajo demanda fijado a FortiOS 7.6.8 y un host Ubuntu detrás. La
  entrada se limita a la variable obligatoria `admin_cidrs`; ya no hay puerto
  abierto a `0.0.0.0/0` ni rol de IAM. El equipo arranca con una configuración
  de ejemplo que incluye debilidades deliberadas documentadas. Validado solo en
  forma estática (`fmt`, `validate`, Checkov): no se ejecutó `plan` ni `apply`,
  y nada fue comprobado contra un equipo en funcionamiento. La conexión privada
  desde la cuenta de PostureGuard (emparejamiento de VPC y Lambda ejecutora en
  una VPC) queda para una fase posterior; mientras tanto la auditoría contra el
  laboratorio se ejecuta con el script local. Detalle en
  [el README del laboratorio](../../infrastructure/fortigate-lab/README.md) y
  [el handoff](handoffs/2026-11-22-fortigate-lab-aws.md). El laboratorio se
  aplicó ese mismo día (ver «Hechos registrados»).
- **Auditorías del laboratorio desde la aplicación (2026-11-22): escrito, sin
  aplicar ni ejecutar.** Dos partes. Red: el módulo nuevo
  `infrastructure/executor-network` crea, en la cuenta del pipeline, una VPC
  privada para la Lambda ejecutora con puntos de enlace de S3, Secrets Manager
  y SNS, y solicita un emparejamiento con la VPC del laboratorio; el
  laboratorio lo acepta con la variable nueva `peering_connection_id`. El
  pipeline no cambia: recibe valores para variables que ya tenía. Aplicación:
  la API local acepta `serve --aws-bridge`, un ciclo opcional que envía a S3 y
  recupera reportes, y la aplicación de escritorio inicia la API con esa
  opción cuando no hay una en ejecución. Validado con `terraform validate`,
  Checkov y tests locales; **no se ejecutó `plan` ni `apply`, no se contactó
  AWS ni el FortiGate, y el flujo completo no se probó**. Quedan seis pasos
  del dueño, dos de ellos a mano en el equipo y en Secrets Manager. Detalle en
  [el README de la red](../../infrastructure/executor-network/README.md) y
  [el handoff](handoffs/2026-11-22-gui-driven-lab-audits.md).
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
| 2026-11-22 | Existe un diagnóstico de solo lectura de la forma de las respuestas del FortiGate (`scripts/diagnose_fortigate_local.py`), fuera del paquete de la Lambda y sin acceso a AWS. Suite del motor en Windows: 572 aprobados y 1 omitido | Commit `7673cfa` y [handoff](handoffs/2026-11-22-fortigate-shape-diagnostic.md); corrida local con HTTP simulado, sin AWS ni FortiGate |
| 2026-11-22 | Recursos desplegados comprobados con lecturas: tres Lambdas `pps-prod-*`, tres buckets, base de conocimientos `ACTIVE` con dos ingestas en `COMPLETE` y una en `STOPPED`, 26 objetos en el bucket de conocimiento (24 documentos y 2 archivos de metadatos), generador con `AUTO_EXECUTE=true`, executor fuera de VPC. El reporte que la Lambda dejó para la segunda corrida está en `could_not_audit` con `preparation_error:ValueError` | Observado en AWS con comandos de solo lectura al escribir [la guía de puesta en marcha](puesta-en-marcha-desde-cero.md); [handoff](handoffs/2026-11-22-puesta-en-marcha-desde-cero.md) |
| 2026-11-22 | El módulo `infrastructure/fortigate-lab` fue reescrito como laboratorio desechable de tres zonas en `us-east-1`. `terraform validate` aprobado; Checkov: 74 aprobadas y 8 fallidas justificadas. No aplicado en AWS | Rama `feature/fortigate-lab-aws`, commit `0727679` y [handoff](handoffs/2026-11-22-fortigate-lab-aws.md); verificación local, sin AWS ni FortiGate |
| 2026-11-22 | El laboratorio se aplicó en la cuenta de laboratorio (`us-east-1`): 37 recursos creados. La administración por HTTPS y la página de demostración reenviada al host Ubuntu respondieron HTTP 200 desde la estación autorizada. Pendiente: primer inicio de sesión, token y primera auditoría contra el equipo | `terraform plan` y `terraform apply` del 2026-11-22; [handoff](handoffs/2026-11-22-fortigate-lab-aws.md) |
| 2026-11-22 | Existen el módulo `infrastructure/executor-network` (red privada del executor y emparejamiento con el laboratorio), la aceptación opcional del emparejamiento en el laboratorio, el ciclo `serve --aws-bridge` de la API local y el inicio de la API desde la aplicación de escritorio. `terraform validate` aprobado en los dos módulos; Checkov: 31 aprobadas y 2 fallidas justificadas en `executor-network`, 76 y 8 en el laboratorio. Tests en Windows: API local 52 aprobados, GUI 65 aprobados. No aplicado en AWS y sin prueba de punta a punta | Rama `feature/gui-driven-lab-audits` y [handoff](handoffs/2026-11-22-gui-driven-lab-audits.md); verificación local, sin AWS ni FortiGate |
| 2026-11-22 | Diagnóstico ejecutado contra un equipo de laboratorio (FortiOS 7.6.8, usuario de API `super_admin_readonly`): `system/admin` y `system/api-user` devuelven HTTP 200 con lista vacía, también con `scope=global`; `system/dhcp/server` y `system/snmp/sysinfo` devuelven HTTP 400 | Informado en el encargo; no observado por el agente que lo registró |
| 2026-11-22 | El toolkit guarda `indeterminate` ante datos ausentes, ilegibles o imposiblemente vacíos (decisión 12) y el catálogo usa `system.dhcp/server` y `system.snmp/sysinfo`. Suites en Windows: motor 620 aprobados y 1 omitido, API local 38, aplicación 51 | Rama `fix/toolkit-absent-data` y [handoff](handoffs/2026-11-22-toolkit-absent-data.md); corrida local con respuestas simuladas, sin AWS ni FortiGate |
| 2026-11-22 | Camino privado aplicado en las dos cuentas (red del executor, emparejamiento de VPC activo, executor dentro de la VPC apuntando al laboratorio, código con el arreglo de datos ausentes). Una auditoría enviada desde la API local terminó `completed` con 17 hallazgos leídos del laboratorio: 9 `pass`, 3 `fail`, 4 `indeterminate`, 1 `not_applicable`. Un intento previo terminó `generation_failed` por rechazo del validador en los tres intentos; el reintento fue aceptado. Pendiente: probar el arranque automático desde la aplicación y completar el `.env` de la estación | `terraform apply` en `executor-network`, `fortigate-lab` y `pipeline`; `aws dispatch` y `aws sync` del 2026-11-22; [handoff](handoffs/2026-11-22-gui-driven-lab-audits.md) |
| 2026-11-22 | Dos corridas contra el laboratorio dejaron entre 4 y 8 de 14 a 17 controles en `indeterminate` por campos que el script pidió y la respuesta no trae | Informado en el encargo; no observado por el agente que lo registró |
| 2026-11-22 | El generador incluye un catálogo de campos de FortiOS 7.6.8 en el prompt de reduce, avisa de campos no listados dentro del ciclo de reintento y registra el detalle de cada rechazo del validador (decisión 13). En la misma rama, cada referencia de la base de conocimientos declara si es técnica o normativa y el reporte lista las técnicas (`propio/`, `fortinet/`) en una sección aparte. Suites en Windows: motor 755 aprobados y 1 omitido, API local 53, aplicación 67. Evals offline (generación y recuperación): código de salida 0 | Rama `feature/generator-field-catalog` y [handoff](handoffs/2026-11-22-generator-field-catalog.md); corrida local con el modelo simulado, sin AWS ni FortiGate |
| 2026-11-23 | Catálogo de campos y tope de anidamiento 4 desplegados. Dos auditorías de control desde la aplicación contra el laboratorio: 15 controles (6 `pass`, 4 `fail`, 4 `indeterminate`, 1 `not_applicable`) y 14 controles (9 `pass`, 2 `fail`, 3 `indeterminate`), ambas con cero referencias a campos desconocidos; los `indeterminate` restantes se deben a `admins` y `api_users` vacíos por el perfil del usuario de API. Antes, una generación terminó `generation_failed` por `max_nesting_exceeded` en los tres intentos. Base de conocimientos: 31 documentos indexados. AWS quedó en pausa: instancias del laboratorio detenidas y accesos internos a Secrets Manager y SNS eliminados | Reportes sincronizados por el puente de la API local; eventos `generation_result` y `generation_attempt_rejected`; [contexto para continuar](handoffs/2026-11-23-contexto-para-continuar.md) |

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
