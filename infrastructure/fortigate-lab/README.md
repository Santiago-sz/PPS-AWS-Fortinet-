# Laboratorio FortiGate en AWS para la demostración de PostureGuard

Terraform que crea un FortiGate-VM y un host Ubuntu detrás de él, en una cuenta
de AWS separada, para que PostureGuard tenga un equipo que auditar durante la
demostración. Todo se elimina con un solo `terraform destroy`.

Estado al 2026-11-22: el código está escrito y validado en forma estática
(`fmt`, `validate`, Checkov). **Todavía no se aplicó en AWS**: nada de lo que
sigue fue comprobado contra un equipo en funcionamiento. Las afirmaciones sin
comprobar están reunidas en [Lo que falta comprobar](#lo-que-falta-comprobar).

## Qué crea

```text
                         Internet
                            |
            solo desde admin_cidrs: TCP 443, 22, 8080
                            |
                   Elastic IP (pública)
                            |
 VPC 10.60.0.0/16 ----------+---------------------------------------------
 |                          |                                            |
 |  subred wan 10.60.0.0/24 (ruta a Internet)                            |
 |                    port1 | 10.60.0.10                                 |
 |                +---------+----------+                                 |
 |                |    FortiGate-VM    |  FortiOS 7.6.8, bajo demanda    |
 |                |      t2.small      |                                 |
 |                +----+----------+----+                                 |
 |          port2 | 10.60.1.10    | port3 10.60.2.10                     |
 |                |               |                                      |
 |  subred lan 10.60.1.0/24       subred dmz 10.60.2.0/24                |
 |  (salida por port2)            (salida por port3)                     |
 |                |               |                                      |
 |        Ubuntu 24.04            (sin equipos: solo objetos             |
 |        10.60.1.20, t3.micro     de ejemplo en el FortiGate)           |
 |        web en el puerto 80                                            |
 -------------------------------------------------------------------------
```

- **Red**: una VPC, una zona de disponibilidad y tres subredes. Solo `wan` tiene
  ruta a Internet. `lan` y `dmz` envían todo su tráfico saliente a la interfaz
  del FortiGate en esa subred.
- **FortiGate-VM**: imagen bajo demanda (PAYG) del Marketplace, fijada a
  FortiOS 7.6.8, la misma versión del equipo real ya probado. Tres interfaces:
  `port1` (wan, con dirección pública fija), `port2` (lan) y `port3` (dmz).
- **Host Ubuntu**: sin dirección pública, sin par de claves y sin acceso remoto.
  Sirve una página de una línea en el puerto 80. El FortiGate la publica en su
  puerto 8080 para mostrar un reenvío de puertos.
- **Acceso**: ninguna regla de entrada admite `0.0.0.0/0`. La interfaz WAN solo
  responde a las direcciones de la variable `admin_cidrs`.
- **Sin pares de claves, sin roles de IAM** y con IMDSv2 obligatorio en las dos
  instancias. Discos cifrados, de tipo gp3.
- **Configuración inicial** del FortiGate: una organización pequeña de ejemplo,
  con debilidades puestas a propósito para que la auditoría encuentre algo.
  Detalle en [Configuración inicial](#configuración-inicial-del-fortigate).

## Lo que no hace todavía

La conexión privada desde la cuenta de PostureGuard (emparejamiento de VPC y la
Lambda ejecutora dentro de una VPC) es una fase posterior. Hoy el laboratorio
solo se alcanza por su dirección pública, desde las direcciones autorizadas, y
la auditoría se ejecuta con el script local. La variable `peer_cidrs` y las
salidas de red (`vpc_id`, `subnet_ids`, `route_table_ids`) ya están preparadas
para esa fase.

## Costo

Valores aproximados por hora con las instancias encendidas, en `us-east-1`:

| Concepto | USD por hora | Nota |
|---|---|---|
| Licencia de FortiGate (Marketplace) | ≈ 0,36 | Tomado de la página del producto, que no indica región: valor aproximado. **Se cobra a la tarjeta y los créditos de AWS no lo cubren** |
| Instancia `t2.small` (FortiGate) | 0,023 | |
| Instancia `t3.micro` (Ubuntu) | 0,0104 | |
| Dirección IPv4 pública | 0,005 | Se cobra también con las instancias detenidas |
| **Total encendido** | **≈ 0,40** | |

Los discos cuestan alrededor de USD 4 por mes aunque las instancias estén
detenidas. Para no pagar nada, destruir el laboratorio.

## Requisitos

1. [Terraform](https://developer.hashicorp.com/terraform/install) 1.5 o
   superior y AWS CLI v2.
2. Sesión en la cuenta de laboratorio:

   ```powershell
   aws login --profile lab-fortigate-pfg
   ```

3. Suscripción al producto del Marketplace, una sola vez por cuenta. Con la
   sesión de la cuenta de laboratorio abierta en la consola web, buscar
   «Fortinet FortiGate Next-Generation Firewall» (versión bajo demanda) en AWS
   Marketplace y aceptar los términos. Sin este paso, `terraform apply` falla
   al crear la instancia. Suscribirse no tiene costo mientras no haya
   instancias encendidas.

## Crear el laboratorio

Todos los comandos se ejecutan en PowerShell, dentro de
`infrastructure/fortigate-lab/`.

1. Indicar la dirección pública desde la que se va a administrar. Es un dato
   privado: **no escribirlo en ningún archivo del repositorio**. Se pasa por
   variable de entorno, solo en la consola abierta:

   ```powershell
   $miIp = (Invoke-RestMethod https://checkip.amazonaws.com).Trim()
   $env:TF_VAR_admin_cidrs = "[`"$miIp/32`"]"
   ```

   `admin_cidrs` es obligatoria, admite hasta 8 bloques y rechaza `0.0.0.0/0`
   y cualquier bloque más amplio que `/16`.

2. Inicializar, revisar y aplicar:

   ```powershell
   terraform init
   terraform plan
   terraform apply
   ```

   Leer el plan antes de confirmar. Debe crear solo recursos nuevos.

3. Anotar las salidas:

   ```powershell
   terraform output
   ```

   Las más usadas: `fortigate_admin_url`, `fortigate_instance_id`,
   `demo_web_url` y `fortigate_ami` (confirma que la imagen es la 7.6.8).

4. Esperar unos minutos. El FortiGate tarda en arrancar y en validar su
   licencia.

El estado de Terraform queda en `terraform.tfstate`, en esta carpeta. Git lo
ignora. Contiene las contraseñas generadas: no copiarlo ni compartirlo.

### Variables

| Variable | Valor por defecto | Uso |
|---|---|---|
| `admin_cidrs` | (obligatoria) | Direcciones públicas autorizadas |
| `peer_cidrs` | `[]` | Bloques de la VPC emparejada, para la fase posterior |
| `aws_profile` | `lab-fortigate-pfg` | Perfil de AWS CLI de la cuenta de laboratorio |
| `aws_region` | `us-east-1` | Región |
| `availability_zone` | primera disponible | Zona de disponibilidad |
| `vpc_cidr` | `10.60.0.0/16` | Bloque de la VPC (debe ser `/16`) |
| `fortios_version` | `7.6.8` | Versión de la imagen del FortiGate |
| `fortigate_instance_type` | `t2.small` | Admite exactamente las 3 interfaces que se usan |
| `ubuntu_instance_type` | `t3.micro` | |
| `fortigate_hostname` | `pg-lab-fgt01` | |
| `api_user_name` | `pps-auditor` | Usuario de REST API de solo lectura |
| `name_prefix` | `pg-lab` | Prefijo de los nombres de los recursos |

## Primer ingreso

1. Abrir `fortigate_admin_url` en el navegador. El certificado es autofirmado:
   el navegador muestra una advertencia.
2. Usuario `admin`. Contraseña inicial: el id de la instancia
   (`terraform output -raw fortigate_instance_id`). Es el comportamiento por
   defecto de la imagen en AWS; no hay par de claves.
3. El equipo obliga a cambiar la contraseña. Elegir una propia, de 12
   caracteres o más, y guardarla en un gestor de contraseñas.
4. Comprobar que la configuración inicial se aplicó: deben verse el nombre de
   host `pg-lab-fgt01`, las tres zonas y doce políticas. Si el equipo aparece
   vacío, ver [Si la configuración inicial no se aplicó](#si-la-configuración-inicial-no-se-aplicó).

Las contraseñas de los administradores adicionales (`netops`, `auditoria`,
`soporte-ext`) se generan al azar. No hacen falta para la demostración. Si se
necesitan:

```powershell
terraform output -json admin_passwords
```

Ese comando muestra contraseñas en pantalla: no ejecutarlo mientras se comparte
la pantalla ni pegar su salida en ningún lado.

## Generar el token de la REST API

El usuario `pps-auditor` ya existe, con el perfil `super_admin_readonly` y
limitado a las direcciones de `admin_cidrs`. Falta generar su token, que solo
se puede hacer en el equipo:

1. En la interfaz web, abrir la consola de comandos (ícono `>_`), o entrar por
   SSH con el usuario `admin`.
2. Ejecutar:

   ```text
   execute api-user generate-key pps-auditor
   ```

3. El token se muestra **una sola vez**.

Tratamiento del token: no pegarlo en conversaciones, correos ni documentos; no
escribirlo en ningún archivo, tampoco en `.env`; no incluirlo en commits ni
pasarlo como argumento de un comando. Se carga solo en la consola que ejecuta
la auditoría, como indica
[la guía de ejecución local, sección 2](../../docs/context/local-executor-run.md#2-tratamiento-del-token).
Si pudo quedar expuesto, repetir el comando: genera uno nuevo e invalida el
anterior.

## Ejecutar una auditoría de PostureGuard

Se usa el script local existente,
`audit-engine/scripts/run_executor_local.py`. La guía completa es
[ejecución local](../../docs/context/local-executor-run.md); acá solo cambia el
equipo de destino.

1. Generar la auditoría por el camino habitual (aplicación de escritorio y
   `pps-api aws dispatch`) y obtener el `run_id`
   ([sección 5 de la guía](../../docs/context/local-executor-run.md#5-obtener-el-run_id)).
2. En una consola de PowerShell, cargar el token como indica la sección 2 de la
   guía y definir las variables. El perfil de AWS es el de la cuenta de
   **PostureGuard**, no el del laboratorio: el script lee el script generado
   desde el bucket de reportes.

   ```powershell
   $env:AWS_PROFILE = "<PERFIL_DE_POSTUREGUARD>"
   $env:AWS_DEFAULT_REGION = "us-east-1"
   $env:S3_BUCKET = "<BUCKET_DE_REPORTES>"
   $env:FORTIGATE_HOST = "<fortigate_public_ip>"
   $env:FORTIGATE_VERIFY_SSL = "false"   # el laboratorio usa un certificado autofirmado
   ```

3. Ejecutar desde `audit-engine/`:

   ```powershell
   ..\.venv\Scripts\python.exe scripts\run_executor_local.py <run_id>
   ```

El script solo lee: hace consultas `GET` al FortiGate y no escribe en AWS. El
reporte queda en `audit-engine/local-runs/`, que Git ignora.

La consola debe salir a Internet con una de las direcciones de `admin_cidrs`.
Si la dirección pública cambió, ver
[Cambio de la dirección de administración](#cambio-de-la-dirección-de-administración).

## Pausar sin destruir

La licencia y las instancias se cobran por hora encendida. Para pausar:

```powershell
$ids = (terraform output -raw fortigate_instance_id), (terraform output -raw ubuntu_instance_id)
aws ec2 stop-instances --instance-ids $ids --profile lab-fortigate-pfg --region us-east-1
```

Para reanudar, el mismo comando con `start-instances`. La dirección pública, la
configuración del FortiGate y el token se conservan. Detenido, el laboratorio
sigue costando los discos y la dirección pública (alrededor de USD 8 por mes en
total).

## Destruir

Un solo comando, en esta carpeta. `admin_cidrs` debe estar definida porque no
tiene valor por defecto; sirve cualquier valor válido:

```powershell
$env:TF_VAR_admin_cidrs = '["192.0.2.1/32"]'
terraform destroy
```

Confirmar que no quedó nada:

```powershell
terraform state list
aws resourcegroupstaggingapi get-resources --tag-filters Key=Component,Values=fortigate-lab --profile lab-fortigate-pfg --region us-east-1 --query "ResourceTagMappingList[].ResourceARN"
aws ec2 describe-addresses --profile lab-fortigate-pfg --region us-east-1 --query "Addresses[].PublicIp"
aws ec2 describe-volumes --filters Name=tag:Component,Values=fortigate-lab --profile lab-fortigate-pfg --region us-east-1 --query "Volumes[].VolumeId"
```

El primero no debe listar nada y los otros tres deben devolver `[]`. El segundo
puede seguir mostrando las instancias terminadas durante un rato: una instancia
en estado `terminated` ya no genera costo. Todos los recursos llevan las
etiquetas `Project=PostureGuard`, `Component=fortigate-lab` y
`ManagedBy=terraform`.

La suscripción del Marketplace sigue activa después de destruir. No genera
costo sin instancias; se puede cancelar desde la consola de AWS Marketplace.

## Configuración inicial del FortiGate

El archivo [`bootstrap/fortigate.conf.tftpl`](bootstrap/fortigate.conf.tftpl)
se entrega como *user-data* y FortiOS lo aplica **una sola vez**, en el primer
arranque. Representa una organización pequeña y completa las áreas que
PostureGuard consulta (los 31 endpoints de
`audit-engine/executor/fortigate_client.py`):

| Área | Contenido |
|---|---|
| Sistema | Nombre de host, zona horaria, tiempo de sesión, bloqueo por intentos fallidos |
| Interfaces y zonas | `port1`, `port2` y `port3` con alias, rol y accesos de administración; zonas `zona-wan`, `zona-lan` y `zona-dmz` |
| Objetos | 13 direcciones (redes, rangos y servidores que no existen como equipos), las direcciones de `admin_cidrs` y `peer_cidrs`, 4 grupos de direcciones, 2 servicios propios y 3 grupos de servicios |
| Políticas | 12 políticas entre zonas: 10 de permiso, 1 de bloqueo y 1 deshabilitada |
| Publicación | VIP `vip-web-demo`: puerto 8080 de la WAN hacia el puerto 80 del host Ubuntu, solo desde `admin_cidrs` |
| Administradores | `netops` (perfil `prof_admin`), `auditoria` (perfil propio de solo lectura `pg-solo-lectura`) y `soporte-ext` (`super_admin`) |
| REST API | Usuario `pps-auditor`, perfil `super_admin_readonly`, limitado a `admin_cidrs` y `peer_cidrs` |
| Usuarios | Dos usuarios locales (uno deshabilitado) y un servidor LDAP de ejemplo |
| Red | DNS, NTP, una ruta estática de ejemplo y un servidor DHCP en la LAN |
| Registro | Registro en memoria, envío por syslog a un servidor de ejemplo, registro de la política implícita |
| SNMP | Datos del sistema (`sysinfo`), sin comunidades |

No se configuran VPN, alta disponibilidad, SD-WAN, FortiAnalyzer, RADIUS ni
administración central: esos endpoints devolverán los valores de fábrica.

### Debilidades puestas a propósito

Están para que la auditoría tenga algo que encontrar. Ninguna amplía la
exposición real: el grupo de seguridad de AWS sigue limitando la entrada a
`admin_cidrs`, la interfaz WAN solo admite HTTPS, SSH y ping, y no se modificó
el cifrado de la interfaz de administración.

La columna «Hallazgo esperado» es una **previsión, no un resultado
comprobado**: depende de la normativa que se cargue y del script que genere el
modelo, y todavía no se ejecutó ninguna auditoría contra este laboratorio.

| Id | Debilidad | Dónde está configurada | Hallazgo esperado (no verificado) |
|---|---|---|---|
| D1 | Sesión de administración inactiva durante 480 minutos, el máximo | `config system global`, `admintimeout` | Tiempo de inactividad excesivo |
| D2 | Política de contraseñas sin complejidad ni vencimiento, y con reutilización permitida. La longitud mínima es 12 porque FortiOS 7.6.8 no admite menos | `config system password-policy` | Complejidad y vencimiento de contraseñas insuficientes |
| D3 | HTTP y Telnet habilitados como accesos de administración, solo en la interfaz LAN | `config system interface`, `port2`, `allowaccess` | Protocolos de administración sin cifrar |
| D4 | Política que permite todo origen, todo destino y todo servicio de la LAN a Internet, sin registro (`LAN-Internet-Temporal-Proveedor`, id 11) | `config firewall policy` | Regla demasiado amplia y sin registro |
| D5 | Política con el registro de tráfico deshabilitado (`DMZ-LAN-BaseDatos`, id 7) | `config firewall policy` | Política sin registro |
| D6 | Administrador `soporte-ext` con perfil `super_admin` y sin orígenes de confianza. El usuario `admin` de fábrica tampoco los tiene | `config system admin` | Administrador sin restricción de origen |
| D7 | Servidor LDAP sin cifrado (puerto 389) | `config user ldap`, `directorio-corp` | Autenticación contra directorio sin cifrar |
| D8 | Bloqueo de cuenta recién tras 10 intentos fallidos y por solo 30 segundos | `config system global`, `admin-lockout-threshold` y `admin-lockout-duration` | Bloqueo por intentos fallidos insuficiente |
| D9 | Usuario local deshabilitado que no se eliminó (`mgomez`) y política deshabilitada heredada (id 12) | `config user local`, `config firewall policy` | Cuentas y reglas sin uso |
| D10 | Solo 4 de las 10 políticas de permiso tienen perfiles de seguridad (antivirus, IPS o filtrado web) | `config firewall policy` | Cobertura baja de perfiles de seguridad |

Fuera de la tabla, sin intención de debilidad: el envío de registros por syslog
usa UDP sin cifrar hacia un servidor que no existe, y DNS se consulta sin
cifrar al servidor de la VPC.

### Contraseñas dentro del user-data

Las contraseñas generadas de los tres administradores y de los dos usuarios
locales viajan dentro del *user-data* de la instancia. Quien tenga permiso para
leer los atributos de la instancia en la cuenta de laboratorio puede verlas.
Es aceptable para un laboratorio desechable en una cuenta aislada; no usar este
esquema fuera de ese contexto.

### Si la configuración inicial no se aplicó

En la consola del equipo:

```text
diagnose debug cloudinit show
```

Muestra qué comandos se ejecutaron y cuáles fallaron. Una línea rechazada no
debería impedir el resto, pero conviene revisar la salida completa. Corregido
el archivo, recrear solo el FortiGate:

```powershell
terraform apply -replace=aws_instance.fortigate
```

Recrearlo cambia el id de la instancia (y con él la contraseña inicial) y
obliga a generar el token otra vez.

### Cambios posteriores

Terraform ignora a propósito los cambios en la configuración inicial y en la
imagen del FortiGate una vez creado, porque FortiOS no vuelve a leer el
*user-data*. Para aplicar un cambio en cualquiera de los dos, usar el comando
`-replace` anterior.

### Cambio de la dirección de administración

Si la dirección pública de quien administra cambia:

1. Definir `TF_VAR_admin_cidrs` con la nueva dirección y ejecutar
   `terraform apply`. Actualiza el grupo de seguridad, sin tocar las instancias.
2. En el FortiGate, entrar con `admin` y actualizar a mano los orígenes de
   confianza del usuario `pps-auditor` (*System > Administrators*) y la
   dirección `adm-origen-1`. Terraform no modifica un equipo ya creado.

## Verificación

No requiere credenciales ni contacta AWS:

```powershell
$env:TF_DATA_DIR = "C:/Users/<usuario>/.terraform-data/pps-fortigate-lab"
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate
```

Resultado del 2026-11-22 con Terraform 1.15.9 y los proveedores aws 6.44.0,
random 3.9.1 y cloudinit 2.4.1: `Success! The configuration is valid.`

Checkov 3.2.379 sobre esta carpeta, el mismo día: 74 comprobaciones aprobadas y
8 fallidas, aceptadas para un laboratorio desechable:

| Comprobación | Recurso | Motivo |
|---|---|---|
| `CKV_AWS_126` (monitoreo detallado) | Las dos instancias | Costo adicional sin uso en la demostración |
| `CKV_AWS_135` (optimización para EBS) | Las dos instancias | `t2.small` no la admite; sin efecto en `t3.micro` |
| `CKV2_AWS_41` (rol de IAM en la instancia) | Las dos instancias | A propósito: ninguna instancia necesita permisos de AWS |
| `CKV2_AWS_11` (registros de flujo de la VPC) | VPC | Costo adicional sin uso en la demostración |
| `CKV2_AWS_19` (Elastic IP asociada a una instancia) | Elastic IP | Está asociada a la interfaz de red del FortiGate; Checkov no sigue esa relación |

Una validación estática no demuestra que el despliegue funcione.

## Lo que falta comprobar

Se comprueba recién al aplicar por primera vez:

- Que la imagen 7.6.8 se resuelve con el código de producto y el patrón de
  nombre, y que acepta volúmenes cifrados en el lanzamiento.
- Que FortiOS 7.6.8 aplica un *user-data* en formato MIME con una sola parte.
  El formato se copió de la plantilla oficial de Fortinet para AWS, que usa dos
  partes (configuración y licencia); la imagen bajo demanda no lleva licencia.
- Que `t2.small` (2 GB de memoria) admite los perfiles de seguridad asignados
  en las políticas 1, 2, 3 y 6.
- Los nombres que se dan por existentes de fábrica: los servicios `HTTP`,
  `HTTPS`, `DNS`, `NTP`, `SSH`, `RDP`, `PING`, `SNMP`, `SYSLOG`, `MYSQL`,
  `SMTPS`, `IMAPS`, `TELNET`, `FTP` y `ALL`; los perfiles `default` de
  antivirus, IPS y filtrado web; el perfil `certificate-inspection`; los
  perfiles de administración `prof_admin`, `super_admin` y
  `super_admin_readonly`; la agenda `always`.
- El valor de zona horaria `America/Argentina/Buenos_Aires`: la referencia de
  7.6.8 indica que el campo es un nombre de la base de zonas horarias, pero no
  publica la lista.
- Que la contraseña inicial de `admin` es el id de la instancia y que el
  comando `diagnose debug cloudinit show` existe en la imagen de AWS (la
  documentación de Fortinet lo describe para otras nubes).
- Que el servicio web del host Ubuntu arranca y responde a través del reenvío.

La sintaxis del resto de los comandos se contrastó con la
[referencia de la CLI de FortiOS 7.6.8](https://docs.fortinet.com/document/fortigate/7.6.8/cli-reference).
El uso de IMDSv2 por FortiGate-VM en AWS está documentado
[desde FortiOS 6.4.3](https://docs.fortinet.com/document/fortigate/6.4.0/new-features/249009/imdsv2-for-fortigate-vm-on-aws-6-4-3).

## Archivos

```text
versions.tf      Versiones de Terraform y de los proveedores
provider.tf      Perfil, región y etiquetas por defecto
variables.tf     Variables y sus validaciones
network.tf       VPC, subredes, gateway y tablas de rutas
security.tf      Grupos de seguridad
fortigate.tf     Imagen, interfaces, dirección pública e instancia del FortiGate
ubuntu.tf        Host Ubuntu
outputs.tf       Salidas
bootstrap/       Configuración inicial del FortiGate y del host Ubuntu
```
