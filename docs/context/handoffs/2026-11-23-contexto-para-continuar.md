# Contexto para continuar: laboratorio en pausa y auditorías desde la aplicación

- Fecha e identificador: 2026-11-23, contexto-para-continuar.
- Propósito: que una persona o un agente retome el trabajo sin leer la
  conversación completa. Resume lo hecho el 2026-11-22 y la madrugada del
  2026-11-23, el estado en que quedó AWS y los pasos exactos para reanudar.
- Rama con todo integrado: `integration/lab-demo` (publicada en `origin`, sin
  unir a `master`). Es la que está desplegada en AWS.
- Estado de AWS al cerrar: **en pausa** (ver «Qué quedó en pausa»).

## Resumen en una página

1. Existe un laboratorio FortiGate-VM (FortiOS 7.6.8, licencia por hora) con un
   host Ubuntu detrás, en una segunda cuenta de AWS (perfil `lab-fortigate-pfg`).
2. La cuenta de PostureGuard (perfil `pps-tesis`) llega al laboratorio por un
   camino privado: red propia para el executor, emparejamiento de VPC entre
   cuentas y accesos internos a S3, Secrets Manager y SNS.
3. La aplicación de escritorio inicia sola la API local con el puente a AWS:
   cargar una normativa en la aplicación alcanza para auditar el laboratorio y
   ver el resultado. Comprobado con auditorías reales.
4. El toolkit ya no entrega veredictos sobre datos que no pudo leer: los marca
   `indeterminate` con el motivo.
5. El generador recibe el catálogo real de campos de FortiOS 7.6.8 y dejó de
   inventar nombres de campos en las dos corridas de control.
6. La base de conocimientos de Bedrock pasó de 24 a 31 documentos indexados.

## Resultados medidos contra el laboratorio

Misma normativa (DA 641/2021, Anexo I) y mismo equipo. Cada fila es una
corrida; el guion se genera de nuevo cada vez, por lo que la cantidad de
controles varía. Son evidencia de casos, no una medición estadística.

| Momento | Controles | `pass` | `fail` | `indeterminate` | Otros | Observación |
|---|---|---|---|---|---|---|
| Ejecución local, sin el arreglo | 14 | 7 | 7 | 0 | 0 | Dos `pass` falsos sobre administradores en cero |
| Ejecución local, con el arreglo | 14 | 2 | 4 | 8 | 0 | 3 por tabla de administradores vacía, 5 por campos inexistentes |
| Desde AWS, con el arreglo | 17 | 9 | 3 | 4 | 1 | Primera corrida por el camino privado |
| Desde la aplicación (1) | 15 | 6 | 2 | 7 | 0 | Campos inventados: `min-length`, `status` (NTP), `zone` |
| Desde la aplicación (2) | 14 | 5 | 2 | 7 | 0 | Ídem |
| Con catálogo de campos (1) | 15 | 6 | 4 | 4 | 1 | Cero referencias a campos desconocidos |
| Con catálogo de campos (2) | 14 | 9 | 2 | 3 | 0 | Cero referencias a campos desconocidos |

En las dos corridas con catálogo, todos los `indeterminate` que quedan tienen la
misma causa: las tablas `admins` y `api_users` llegan vacías (ver «Pendientes»,
punto 1).

Dos generaciones de las ocho lanzadas terminaron `generation_failed`: el
validador rechazó los tres intentos por un nivel de anidamiento de más
(`max_nesting_exceeded`, profundidad 4 con tope 3). El tope se subió a 4
(commit `5059c57`) y las dos generaciones posteriores fueron aceptadas en el
primer intento. Dos corridas no alcanzan para afirmar que el fallo no vuelva.

## Hallazgos técnicos que conviene tener presentes

- **Visibilidad por perfil.** En FortiOS 7.6.8, un usuario de API con perfil
  `super_admin_readonly` recibe HTTP 200 con lista vacía en `system/admin` y
  `system/api-user` (también con `scope=global`), y la respuesta declara
  `matched_count` 1. Con perfil `super_admin` devuelve las entradas, y además
  expone campos de contraseña y de clave. No es un defecto del guion.
- **Rutas corregidas.** `system.dhcp/server` y `system.snmp/sysinfo` (antes con
  barra, respondían HTTP 400). La ruta de SNMP se dedujo por analogía y todavía
  no se comprobó contra el equipo.
- **Configuración inicial del laboratorio.** Solo existe el administrador
  `admin`: la sección de administradores del `bootstrap` no parece haberse
  cargado. Sin confirmar. El resto (zonas, políticas, usuarios locales, LDAP,
  syslog, reenvío al host Ubuntu) sí está presente.
- **Errores de lógica del guion no detectados.** Un guion informó «144 VDOM»
  al contar los campos de `system/settings`. El harness no detecta este tipo
  de error.
- **Precedencia de variables en el pipeline.** `terraform.tfvars` (ignorado
  por Git) fija `fortigate_host` y prevalece sobre `TF_VAR_*`. Los cuatro
  valores del laboratorio deben pasarse con `-var` en cada `apply`.
- **Memoria de la estación.** Con cerca de 1 GB de RAM libre, el proveedor de
  AWS de Terraform falla con «Plugin did not respond». Reintentar; sirvió
  `-parallelism=2`.
- **Git Bash y rutas de CloudWatch.** Anteponer `MSYS_NO_PATHCONV=1` a los
  comandos de `aws logs` con grupos que empiezan con `/`.

## Qué quedó en pausa

| Recurso | Cuenta | Estado | Costo mientras está en pausa |
|---|---|---|---|
| Instancia FortiGate | Laboratorio | Detenida | Sin licencia ni cómputo; discos e IP fija, centavos por día |
| Instancia Ubuntu | Laboratorio | Detenida | Solo disco |
| Accesos internos a Secrets Manager y SNS | PostureGuard | Eliminados (`enable_interface_endpoints=false`) | Cero |
| Red del executor, emparejamiento, acceso a S3 | PostureGuard | Activos | Cero |
| Funciones del pipeline, buckets, base de conocimientos | PostureGuard | Activos, sin uso | Según uso |

Nada se destruyó. La contraseña de `admin`, el token de `pps-auditor`, el host
de confianza `10.61.0.0/24` y el secreto en AWS siguen vigentes: al encender no
hay que repetir pasos manuales.

**Mientras esté en pausa no deben lanzarse auditorías**: el executor no llega al
equipo ni a Secrets Manager, y el resultado sería una auditoría fallida o con
todos los controles `indeterminate`.

## Cómo reanudar

Desde Git Bash, en la raíz del repositorio. Los identificadores salen de
`terraform output` en cada módulo; no se escriben en archivos versionados.

1. Sesión de la cuenta de laboratorio (credenciales temporales, hasta 12 horas;
   el propietario aprueba en el navegador):

   ```bash
   aws login --profile lab-fortigate-pfg
   ```

2. Encender las dos instancias del laboratorio:

   ```bash
   cd infrastructure/fortigate-lab
   export TF_DATA_DIR="C:/Users/<usuario>/.terraform-data/pps-fortigate-lab"
   aws ec2 start-instances --profile lab-fortigate-pfg --region us-east-1 \
     --instance-ids "$(terraform output -raw fortigate_instance_id)" "$(terraform output -raw ubuntu_instance_id)"
   ```

   El FortiGate tarda unos cinco minutos en responder. La IP pública no cambia.

3. Volver a crear los accesos internos en la cuenta de PostureGuard:

   ```bash
   cd ../executor-network
   export TF_DATA_DIR="C:/Users/<usuario>/.terraform-data/pps-executor-network"
   export TF_VAR_peer_account_id="<ID_CUENTA_LABORATORIO>" TF_VAR_peer_vpc_id="<VPC_DEL_LABORATORIO>"
   terraform apply -parallelism=2 -var "peering_accepted=true"
   ```

   El plan esperado agrega dos recursos y no modifica ni destruye nada.

4. Si la IP pública de la estación cambió, volver a aplicar el laboratorio con
   todas las direcciones autorizadas en `TF_VAR_admin_cidrs`, además de
   `TF_VAR_peer_cidrs='["10.61.0.0/24"]'` y `TF_VAR_peering_connection_id`.
   Solo afecta el acceso a la administración web desde la estación; las
   auditorías desde AWS no dependen de esa IP.

5. Abrir la aplicación, que inicia la API local con el puente a AWS:

   ```powershell
   .\.venv\Scripts\python.exe gui\launch.py
   ```

   Debe mostrar «Envío automático a AWS activo». Requiere que el `.env` de la
   raíz defina `AWS_PROFILE`, `AWS_DEFAULT_REGION`, `PPS_POLICIES_BUCKET` y
   `PPS_REPORTS_BUCKET`.

Para volver a pausar: detener las dos instancias con `aws ec2 stop-instances` y
aplicar `executor-network` con `-var "peering_accepted=true" -var
"enable_interface_endpoints=false"`. Para eliminar todo, seguir el orden de
[`infrastructure/executor-network/README.md`](../../../infrastructure/executor-network/README.md).

## Pendientes, en orden sugerido

1. **Perfil de solo lectura que vea administradores.** Definir en el FortiGate
   un perfil a medida para `pps-auditor` que permita leer `system/admin` y
   `system/api-user` sin exponer escritura, comprobarlo con
   `diagnose_fortigate_local.py --only admins,api_users` e incorporarlo al
   `bootstrap` del laboratorio y a la documentación de requisitos del equipo.
   Es lo único que hoy deja controles en `indeterminate`.
2. **Volver a ejecutar el diagnóstico completo** contra el laboratorio para
   confirmar las rutas de DHCP y SNMP y completar el catálogo; `vpn_ipsec` y
   `radius_servers` necesitan al menos una entrada en el equipo.
3. **Confirmar la carga del `bootstrap`**: revisar `System → Administrators` y,
   si faltan los administradores previstos, corregir la plantilla.
4. **Regrabar las evaluaciones en vivo** (`evals/run_evals.py --mode live
   --record`), porque las grabaciones son anteriores al catálogo de campos.
5. **Revisión de los autores y unión a `master`**: el aumento del tope de
   anidamiento (commit `5059c57`) modifica un límite del validador y necesita
   aprobación explícita. También `NEVER_EMPTY_ENDPOINTS` (decisión 12).
6. **Evidencia para la tesis**: capturas de la aplicación y de la consola con
   las corridas nuevas, y comparación antes y después.
7. **Fuentes manuales del corpus**: CIS FortiGate Benchmark y CCN-STIC-1406.

## Dónde está cada cosa

| Tema | Documento |
|---|---|
| Laboratorio | [`infrastructure/fortigate-lab/README.md`](../../../infrastructure/fortigate-lab/README.md), [handoff](2026-11-22-fortigate-lab-aws.md) |
| Camino privado y modo de una sola ventana | [`infrastructure/executor-network/README.md`](../../../infrastructure/executor-network/README.md), [handoff](2026-11-22-gui-driven-lab-audits.md) |
| Datos ausentes | [decisión 12](../decisions/12-datos-ausentes-indeterminate.md), [handoff](2026-11-22-toolkit-absent-data.md) |
| Catálogo de campos y tipos de referencia | [decisión 13](../decisions/13-catalogo-de-campos-generador.md), [handoff](2026-11-22-generator-field-catalog.md) |
| Base de conocimientos | [`docs/context/rag/corpus.md`](../rag/corpus.md) |
| Estado general | [`status.md`](../status.md) |

## Ramas

| Rama | Contenido | Estado |
|---|---|---|
| `feature/fortigate-lab-aws` | Laboratorio | Publicada |
| `feature/gui-driven-lab-audits` | Red del executor, puente a AWS, arranque desde la aplicación | Publicada |
| `fix/toolkit-absent-data` | `indeterminate` ante datos ausentes, rutas corregidas | Publicada |
| `feature/generator-field-catalog` | Catálogo de campos, registro de rechazos, tipos de referencia | Incluida en la de integración |
| `integration/lab-demo` | Une las cuatro, más el tope de anidamiento y la documentación | Publicada y desplegada |

Verificación local sobre `integration/lab-demo`: motor 756 aprobadas y 1
omitida; API local 53; aplicación 67; `ruff` sin observaciones en las rutas del
motor; evaluaciones sin conexión con código de salida 0. La integración continua
en Linux no se ejecutó.
