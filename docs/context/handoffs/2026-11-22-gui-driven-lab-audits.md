# Auditorías del laboratorio desde la aplicación de escritorio

- Fecha e identificador: 2026-11-22, gui-driven-lab-audits.
- Estado: código y documentación escritos; validado en forma estática y con
  tests locales. **Nada se aplicó ni se ejecutó contra AWS ni contra un
  equipo**: no se corrió `terraform plan`, `apply` ni `destroy`, no se hizo
  ninguna llamada a AWS y no se contactó el FortiGate. El flujo completo no se
  probó.
- Rama: `feature/gui-driven-lab-audits`, creada desde
  `feature/fortigate-lab-aws` en `7a024bf` por pedido del encargo (el
  laboratorio todavía no está integrado en `master`). Es una excepción a la
  regla de partir de `master`: al integrar, el laboratorio va primero.
- Commits propios: ver `git log feature/fortigate-lab-aws..feature/gui-driven-lab-audits`.
- Revisión del desarrollador y merge: pendientes. Push: no realizado.
- Actualización posterior (2026-11-22, misma jornada): la conexión se aplicó en
  las dos cuentas desde la rama `integration/lab-demo`, que une este trabajo con
  `fix/toolkit-absent-data`. Resultado por paso: `executor-network`, 15 recursos
  creados; laboratorio, 3 agregados y ninguna modificación de instancias;
  ruta al laboratorio creada y emparejamiento en estado `active`; host de
  confianza `10.61.0.0/24` agregado a mano en el usuario de API; secreto del
  token actualizado por el propietario; pipeline, 1 agregado y 3 funciones
  actualizadas (executor dentro de la VPC, `FORTIGATE_HOST=10.60.0.10`,
  `FORTIGATE_VERIFY_SSL=false` y código con el arreglo de datos ausentes).
- Prueba de punta a punta (2026-11-22): una reauditoría creada en la API local,
  enviada con `aws dispatch` y recuperada con `aws sync`, terminó `completed`
  con 17 hallazgos leídos del equipo de laboratorio por el camino privado
  (9 `pass`, 3 `fail`, 4 `indeterminate`, 1 `not_applicable`). El primer intento
  del mismo día terminó `generation_failed`: los tres intentos del modelo fueron
  rechazados por la lista de permitidos del validador; el código del generador
  y del validador no cambió, y el reintento inmediato fue aceptado. La causa
  del rechazo no quedó registrada (el log solo guarda la clase de fallo).
- Hallazgo operativo: `terraform.tfvars` del pipeline fija `fortigate_host` y
  tiene precedencia sobre `TF_VAR_fortigate_host`. Para apuntar al laboratorio
  los cuatro valores deben pasarse con `-var` en cada `apply` del pipeline.
- Sin probar todavía: el arranque automático de la API desde la ventana de la
  aplicación. En la estación usada, `serve --aws-bridge` termina con código 2
  porque el `.env` de la raíz no define `PPS_POLICIES_BUCKET`; el propietario
  debe completarlo.

## Objetivo y aceptación

Pedido: «con solo la aplicación de escritorio abierta, lanzar una auditoría
contra el FortiGate de laboratorio y ver el resultado». Dos partes:

1. **Camino de red** entre la Lambda ejecutora (cuenta del pipeline) y el
   FortiGate (cuenta de laboratorio). Diseño ya elegido en el encargo:
   emparejamiento de VPC entre cuentas.
2. **Operación en una ventana**: que la aplicación inicie la API local y que la
   API envíe a S3 y recupere los reportes sin comandos manuales, como opción y
   sin cambiar el envío explícito por defecto.

Restricciones del encargo: sin `plan`, `apply` ni `destroy`; sin llamadas a
AWS; sin contacto con el FortiGate; sin leer `.env`, `*.tfvars`, estados de
Terraform ni reportes locales; sin tocar `audit-engine/` (otra tarea trabaja en
`fix/toolkit-absent-data`); sin cambiar `.tf` del pipeline salvo necesidad
estricta; sin push ni merge.

## Cambios preexistentes y propios

Árbol limpio al empezar. Cambios propios:

- `infrastructure/executor-network/` (nuevo): VPC `10.61.0.0/24` con una subred
  privada, sin gateway de Internet ni NAT; grupo de seguridad de la Lambda con
  salida solo por TCP 443 al FortiGate, a los puntos de enlace y a S3; punto de
  enlace de S3 (gateway); puntos de enlace de Secrets Manager y SNS (interfaz)
  detrás de `enable_interface_endpoints`; solicitud de emparejamiento; ruta al
  laboratorio detrás de `peering_accepted`.
- `infrastructure/fortigate-lab/`: variable `peering_connection_id`; con valor,
  acepta el emparejamiento y agrega una ruta por cada bloque de `peer_cidrs` en
  la tabla de `wan`. Vacía, no crea nada.
- `infrastructure/pipeline/`: sin cambios. Recibe valores para variables que ya
  existían (`fortigate_host`, `fortigate_verify_ssl`, `executor_subnet_ids`,
  `executor_security_group_ids`).
- `local-api/pps_api/aws/worker.py` (nuevo) y `__main__.py`:
  `serve --aws-bridge [--aws-bridge-interval SEGUNDOS]`.
  `services/policies.py`: `capabilities.automatic_dispatch` en la sesión.
- `gui/pps_desktop/local_server.py` (nuevo) y `app.py`: inicio y fin del
  proceso de la API, estado en Configuración y en el aviso superior, opción
  `--no-local-api`.
- Documentación: README de `executor-network`, del laboratorio, de la API local
  y de la GUI; `gui/API_CONTRACT.md`; `AGENTS.md`; `repository-layout.md`;
  `status.md`; este handoff y su índice.

## Decisiones

- **El laboratorio no reemplaza la instancia al aceptar el emparejamiento.**
  Comprobado leyendo el código: los recursos nuevos (`aws_vpc_peering_connection_accepter`,
  `aws_route.wan_peer`) y la regla de entrada de `peer_cidrs` son recursos
  separados. `peer_cidrs` cambia el texto de la configuración inicial, pero
  `aws_instance.fortigate` tiene `ignore_changes = [ami, user_data]`. Las
  interfaces de red y la dirección pública no dependen de las variables nuevas.
  Falta confirmarlo con un `plan` real.
- **Origen de confianza a mano.** Por lo anterior, el FortiGate ya creado no
  recibe el origen `10.61.0.0/24` del usuario `pps-auditor`; se agrega en el
  equipo con la misma sintaxis de `bootstrap/fortigate.conf.tftpl`.
- **La ruta al laboratorio es un segundo `apply`** (`peering_accepted`), para
  crearla con el emparejamiento ya activo.
- **El ciclo automático no cambia las reglas del puente.** Llama a
  `Bridge.dispatch()` y `Bridge.sync()` tal como están: un envío ambiguo queda
  en `sending` y no se repite; un conflicto por ejecuciones duplicadas queda en
  `conflict`. El cliente de S3 se crea sin reintentos, igual que en los
  comandos explícitos.
- **Fallo al inicio si falta configuración.** `serve --aws-bridge` termina con
  código 2 y un mensaje si faltan buckets, credenciales o el archivo de
  `--env-file`. La aplicación usa ese código para reiniciar la API sin el
  ciclo y avisarlo.
- **Registro sin secretos.** El ciclo registra solo el tipo de excepción y el
  código de error de AWS, nunca el mensaje.
- **La API informa si el envío automático está activo**
  (`capabilities.automatic_dispatch`), para que el aviso de la aplicación sea
  cierto también cuando la API la inició otra persona.
- **La aplicación solo administra `http://127.0.0.1:8765`** y solo termina el
  proceso que ella inició. No se conecta sola si hay una sesión institucional
  guardada.

Skills: no se usaron skills del proyecto; se siguieron `AGENTS.md` y los
manuales de cada componente.

## Estado TDD

- API local: `tests/test_worker.py` escrito primero. Fallo inicial observado:
  `ModuleNotFoundError: No module named 'pps_api.aws.worker'`. Después de
  implementar: 52 aprobados (37 anteriores y 15 nuevos).
- GUI: `tests/test_local_server.py` escrito antes de modificar `app.py`. Fallo
  inicial observado en los 6 tests de la ventana
  (`Window.__init__() got an unexpected keyword argument 'local_server'`). Los
  10 tests del proceso se ejecutaron por primera vez con `local_server.py` ya
  escrito, por lo que no se observó su fallo inicial. Después de implementar:
  65 aprobados (49 anteriores y 16 nuevos).
- Terraform y documentación: sin comportamiento ejecutable; comprobaciones de
  formato, validación y enlaces.

## Verificaciones ejecutadas (2026-11-22, Windows)

- `local-api`: `pytest -q` → 52 aprobados. `ruff check .` limpio.
- `gui`: `QT_QPA_PLATFORM=offscreen pytest -q` → 65 aprobados. `ruff check .`
  limpio.
- `ruff format --check` limpio en los archivos nuevos o modificados (en
  `local-api` con ancho de línea 100, el de los archivos existentes; ese
  paquete no fija configuración de ruff y otros archivos anteriores no están
  formateados).
- `python -m pps_api serve --aws-bridge` sin configuración, en una carpeta
  vacía: termina con código 2 y el mensaje de `PPS_POLICIES_BUCKET`. No
  contacta AWS.
- `infrastructure/executor-network`: `terraform fmt`, `init -backend=false` y
  `validate` → `Success! The configuration is valid.` (Terraform 1.15.9,
  aws 6.73.0). Checkov 3.2.379: 31 aprobadas, 2 fallidas justificadas en su
  README.
- `infrastructure/fortigate-lab`: `fmt`, `init -backend=false` y `validate` →
  `Success! The configuration is valid.` (aws 6.44.0, sin cambios en el lock).
  Checkov: 76 aprobadas y 8 fallidas, las mismas 8 de antes.
- `TF_DATA_DIR` usado: `~/.terraform-data/validate-executor-network` y
  `~/.terraform-data/validate-fortigate-lab`, distintos del directorio real del
  laboratorio.

Observación: una corrida de la suite de la API local tardó 128 s y falló en dos
tests anteriores de `test_api.py` (`test_invalid_metadata_returns_client_error`
con `size=-1` y `sha256=wrong`). No se reprodujo: pasan solos y en las dos
corridas completas siguientes (11,8 s y 16,4 s). La causa no se investigó;
la estación tenía poca memoria libre.

No ejecutado: la suite de `audit-engine` (no se tocó ese componente ni los
`.tf` del pipeline), la aplicación con ventana real iniciando la API, y todo lo
que requiere AWS o el equipo.

## Pendientes y próximo paso

Pasos del dueño, en orden, detallados en
[el README de la red](../../infrastructure/executor-network/README.md#procedimiento):

1. `apply` de `executor-network` (crea la red y solicita el emparejamiento).
2. `apply` del laboratorio con `peer_cidrs`, `peering_connection_id` y
   `admin_cidrs` completo. Revisar que el plan no toque la instancia.
3. `apply` de `executor-network` con `peering_accepted=true`.
4. A mano en el FortiGate: origen de confianza `10.61.0.0 255.255.255.0` para
   `pps-auditor`.
5. A mano: token en el secreto `pps-prod-fortigate-token`.
6. `apply` del pipeline con los cuatro valores.

Después: abrir la aplicación, cargar una normativa y comprobar el reporte.

Sin comprobar, además de lo anterior:

- Que la Lambda dentro de la subred llega a S3, Secrets Manager y SNS por los
  puntos de enlace, y que no necesita otro servicio de AWS en tiempo de
  ejecución. Se revisó el contrato de `AGENTS.md` (S3, Secrets Manager, SNS);
  los registros y la cola de mensajes fallidos los maneja el servicio Lambda,
  fuera de la red.
- El bloque de PowerShell que carga el token: el tratamiento de las comillas
  depende de la versión de PowerShell. El README incluye una comprobación del
  formato guardado.
- Los costos indicados y el tiempo de liberación de las interfaces de red de
  la Lambda al desarmar.
- El cierre de la API al salir de la aplicación es inmediato (terminación del
  proceso en Windows): el ciclo no llega a detenerse de forma ordenada. Un
  envío en curso en ese instante queda como ambiguo, que es el caso que el
  puente ya contempla.

Próximo paso concreto: revisión del desarrollador de esta rama; luego, con su
autorización, el paso 1 del procedimiento.
