# Red privada de la Lambda ejecutora hacia el laboratorio FortiGate

Terraform que crea, en la cuenta del pipeline de PostureGuard, una red privada
para la Lambda ejecutora (`audit_executor`) y la conecta con la VPC del
[laboratorio FortiGate](../fortigate-lab/README.md), que está en otra cuenta.
Con esto la auditoría completa corre en AWS: la Lambda llega al FortiGate por
su dirección privada, sin pasar por Internet.

Estado al 2026-11-22: el código está escrito y validado en forma estática
(`fmt`, `validate`, Checkov). **No se aplicó en AWS**: no se ejecutó `plan` ni
`apply`, y nada de lo que sigue fue comprobado contra una cuenta ni contra el
equipo. Lo que queda sin comprobar está en
[Lo que falta comprobar](#lo-que-falta-comprobar).

## Qué crea

```text
 Cuenta del pipeline (perfil pps-tesis)        Cuenta de laboratorio (perfil lab-fortigate-pfg)
 us-east-1                                     us-east-1

 VPC 10.61.0.0/24 (este módulo)                VPC 10.60.0.0/16 (infrastructure/fortigate-lab)
 +------------------------------------+        +----------------------------------+
 | subred privada 10.61.0.0/25        |        | subred wan 10.60.0.0/24          |
 | sin gateway de Internet ni NAT     |        |                                  |
 |                                    |        |   FortiGate port1 10.60.0.10     |
 |  Lambda audit_executor  ---TCP 443-+--------+-->  (REST API, solo lectura)     |
 |  (la coloca el módulo pipeline)    | empare-|                                  |
 |      |                             | jami-  | grupo de seguridad: TCP 443      |
 |      | TCP 443                     | ento   | desde peer_cidrs (10.61.0.0/24)  |
 |      v                             | de VPC |                                  |
 |  puntos de enlace:                 |        | ruta 10.61.0.0/24 -> empareja-   |
 |   - S3 (gateway, sin costo)        |        | miento, solo en la tabla de wan  |
 |   - Secrets Manager (interfaz)     |        +----------------------------------+
 |   - SNS (interfaz)                 |
 +------------------------------------+
```

- **Red**: una VPC con una subred privada. No tiene gateway de Internet ni NAT:
  desde esta red no se llega a Internet.
- **Emparejamiento de VPC**: esta cuenta lo solicita y el laboratorio lo
  acepta desde su propio módulo. La ruta hacia el laboratorio se crea recién
  con `peering_accepted = true`.
- **Grupo de seguridad de la Lambda**: sin reglas de entrada. Salida solo por
  TCP 443 hacia la dirección del FortiGate (`10.60.0.10/32`), hacia los puntos
  de enlace de interfaz y hacia S3.
- **Puntos de enlace**: la Lambda ejecutora llama a S3 (lee el script y escribe
  el reporte), a Secrets Manager (lee el token del FortiGate) y a SNS (avisa el
  fin de la auditoría). Sin salida a Internet, necesita un punto de enlace para
  cada uno. El de S3 es de tipo gateway; los otros dos son de tipo interfaz,
  con DNS privado, y dependen de `enable_interface_endpoints`.

Este módulo **no modifica** `infrastructure/pipeline/`. Solo entrega dos
salidas, `executor_subnet_ids` y `executor_security_group_ids`, con la forma de
las variables del mismo nombre que el pipeline ya tiene.

## Costo

Valores aproximados en `us-east-1`, **no verificados** contra la página de
precios:

| Concepto | Costo | Nota |
|---|---|---|
| Punto de enlace de interfaz (Secrets Manager) | ≈ USD 0,01 por hora | Por zona de disponibilidad; se usa una sola |
| Punto de enlace de interfaz (SNS) | ≈ USD 0,01 por hora | Ídem |
| Datos por los puntos de enlace de interfaz | ≈ USD 0,01 por GB | Insignificante en una auditoría |
| Punto de enlace de S3 (gateway) | Sin costo | |
| Emparejamiento de VPC | Sin costo por hora | |
| VPC, subred, tabla de rutas, grupos de seguridad | Sin costo | |
| **Total con los puntos de enlace creados** | **≈ USD 0,02 por hora** | Alrededor de USD 15 por mes si no se pausa |

El único cargo por hora es el de los dos puntos de enlace de interfaz. Se
elimina con `enable_interface_endpoints=false`
(ver [Pausar los cargos](#pausar-los-cargos)).

## Requisitos

1. Terraform 1.5 o superior y AWS CLI v2.
2. El laboratorio ya aplicado (lo está desde el 2026-11-22) y el pipeline ya
   desplegado en la cuenta de PostureGuard.
3. Sesión en las dos cuentas:

   ```powershell
   aws login --profile pps-tesis
   aws login --profile lab-fortigate-pfg
   ```

4. Dos datos del laboratorio. Son privados: **no escribirlos en ningún archivo
   del repositorio**.

   ```powershell
   # Id de la VPC del laboratorio (en infrastructure/fortigate-lab/)
   terraform output -raw vpc_id
   # Id de la cuenta de laboratorio
   aws sts get-caller-identity --profile lab-fortigate-pfg --query Account --output text
   ```

## Procedimiento

Son seis pasos, en este orden. Los comandos se ejecutan en PowerShell. Leer
cada plan antes de confirmar.

Las variables de tipo lista se pasan por variable de entorno (`TF_VAR_...`)
porque Windows PowerShell 5.1 quita las comillas dobles de los argumentos y
Terraform recibiría una lista inválida.

### 1. Crear la red y solicitar el emparejamiento (cuenta del pipeline)

En `infrastructure/executor-network/`:

```powershell
$env:TF_VAR_peer_account_id = "<ID_DE_LA_CUENTA_DE_LABORATORIO>"
$env:TF_VAR_peer_vpc_id     = "<VPC_ID_DEL_LABORATORIO>"
terraform init
terraform plan
terraform apply
terraform output
```

El plan debe crear solo recursos nuevos. Anotar las salidas
`peering_connection_id`, `executor_subnet_ids` y
`executor_security_group_ids`. El emparejamiento queda en estado
`pending-acceptance`.

### 2. Aceptar el emparejamiento (cuenta de laboratorio)

En `infrastructure/fortigate-lab/`:

```powershell
$env:TF_VAR_admin_cidrs           = '["<IP_OPERADOR_1>/32","<IP_OPERADOR_2>/32"]'
$env:TF_VAR_peer_cidrs            = '["10.61.0.0/24"]'
$env:TF_VAR_peering_connection_id = "<peering_connection_id>"
terraform plan
terraform apply
```

**`admin_cidrs` debe llevar todas las direcciones de operador autorizadas
hoy.** Terraform deja el grupo de seguridad igual a la lista que recibe: una
dirección que falte pierde el acceso al FortiGate.

El plan debe mostrar solo recursos a crear: la aceptación del emparejamiento,
una ruta en la tabla de `wan` y una regla de entrada por TCP 443 desde
`10.61.0.0/24`. **No debe reemplazar ni modificar la instancia del FortiGate,
sus interfaces de red ni la dirección pública.** Si el plan indica otra cosa,
no aplicar.

### 3. Crear la ruta hacia el laboratorio (cuenta del pipeline)

En `infrastructure/executor-network/`, con las mismas variables del paso 1:

```powershell
terraform apply -var "peering_accepted=true"
```

El plan debe crear un único recurso: la ruta `10.60.0.0/16` hacia el
emparejamiento. La salida `peering_status` debe decir `active`.

### 4. Autorizar la red nueva en el FortiGate (a mano)

El usuario de REST API `pps-auditor` solo acepta pedidos desde sus orígenes de
confianza. La configuración inicial del equipo se aplica una sola vez, así que
Terraform no agrega el origen nuevo: hay que hacerlo en el equipo.

En la consola del FortiGate (ícono `>_` de la interfaz web, o SSH con `admin`),
ver primero las entradas existentes:

```text
show system api-user pps-auditor
```

Agregar la red de la Lambda con un número de entrada que no esté en uso. La
configuración inicial usa del 1 en adelante, uno por cada dirección de
`admin_cidrs` (hasta 8); el 9 está libre salvo que se haya agregado a mano:

```text
config system api-user
    edit "pps-auditor"
        config trusthost
            edit 9
                set type ipv4-trusthost
                set ipv4-trusthost 10.61.0.0 255.255.255.0
            next
        end
    next
end
```

Repetir el `show` para confirmar que la entrada quedó guardada y que las
anteriores siguen ahí.

### 5. Cargar el token del FortiGate en Secrets Manager (a mano)

El token **no se pega en conversaciones, no se guarda en archivos y no entra
en ningún commit**. Lo escribe solo quien opera, en su propia consola.

1. Si todavía no existe un token, generarlo en el FortiGate. Se muestra una
   sola vez; generar otro invalida el anterior.

   ```text
   execute api-user generate-key pps-auditor
   ```

2. Copiar el token al portapapeles y, en PowerShell, ejecutar este bloque. Lee
   el portapapeles, no muestra el token y limpia las variables al terminar:

   ```powershell
   $token = (Get-Clipboard -Raw).Trim()
   $json  = @{ token = $token } | ConvertTo-Json -Compress
   # Windows PowerShell 5.1 y PowerShell hasta 7.2 quitan las comillas dobles
   # de los argumentos; hay que escaparlas.
   if ($PSVersionTable.PSVersion -lt [version]"7.3") { $json = $json.Replace('"', '\"') }
   aws secretsmanager put-secret-value --secret-id pps-prod-fortigate-token `
     --secret-string $json --profile pps-tesis --region us-east-1 `
     --query VersionId --output text
   Remove-Variable token, json
   Set-Clipboard -Value " "
   ```

3. Comprobar que el secreto quedó con el formato correcto, sin mostrar el
   token:

   ```powershell
   $check = aws secretsmanager get-secret-value --secret-id pps-prod-fortigate-token `
     --profile pps-tesis --region us-east-1 --query SecretString --output text | ConvertFrom-Json
   "Campo token presente: {0}. Longitud: {1}" -f [bool]$check.token, "$($check.token)".Length
   Remove-Variable check
   ```

   Debe informar que el campo está presente y una longitud mayor que cero. Si
   `ConvertFrom-Json` da error, el valor no se guardó como JSON: repetir el
   punto 2.

### 6. Colocar la Lambda ejecutora en la red (cuenta del pipeline)

En `infrastructure/pipeline/`, agregar estos valores a los que ya se usan para
aplicar el pipeline:

| Variable | Valor |
|---|---|
| `fortigate_host` | `10.60.0.10` (dirección privada del FortiGate) |
| `fortigate_verify_ssl` | `false` (el laboratorio usa un certificado autofirmado) |
| `executor_subnet_ids` | La salida `executor_subnet_ids` del paso 1 |
| `executor_security_group_ids` | La salida `executor_security_group_ids` del paso 1 |

Como argumentos `-var` (consola `bash`, `cmd` o PowerShell 7.3 o superior):

```text
terraform plan \
  -var "fortigate_host=10.60.0.10" \
  -var "fortigate_verify_ssl=false" \
  -var 'executor_subnet_ids=["<subnet-...>"]' \
  -var 'executor_security_group_ids=["<sg-...>"]'
```

En Windows PowerShell 5.1, la forma equivalente que no pierde las comillas:

> **Precedencia comprobada el 2026-11-22.** Si `terraform.tfvars` del pipeline
> ya define `fortigate_host` (u otro de estos valores), ese archivo tiene
> precedencia sobre las variables de entorno `TF_VAR_*` y el plan no cambia el
> host. En ese caso los cuatro valores deben pasarse con `-var` en la línea de
> comandos (desde Git Bash las comillas de las listas se conservan), o bien
> editarse en `terraform.tfvars`.

```powershell
$env:TF_VAR_fortigate_host              = "10.60.0.10"
$env:TF_VAR_fortigate_verify_ssl        = "false"
$env:TF_VAR_executor_subnet_ids         = '["<subnet-...>"]'
$env:TF_VAR_executor_security_group_ids = '["<sg-...>"]'
terraform plan
terraform apply
```

El plan debe modificar la Lambda ejecutora (configuración de VPC y variables de
entorno) y agregar a su rol la política administrada
`AWSLambdaVPCAccessExecutionRole`. La Lambda `assessor` del flujo anterior
recibe el mismo `FORTIGATE_HOST`, pero queda fuera de la VPC y su programación
está apagada por defecto.

Estos cuatro valores hay que pasarlos **en cada `apply` posterior del
pipeline**. Si se omiten las dos listas, Terraform saca la Lambda de la red.

Para comprobar el resultado, abrir la aplicación de escritorio, cargar una
normativa y esperar el reporte
([guía de la aplicación](../../gui/README.md#una-sola-ventana)).

## Pausar los cargos

Para dejar de pagar los puntos de enlace sin desarmar el resto, en
`infrastructure/executor-network/` y con las variables del paso 1:

```powershell
terraform apply -var "peering_accepted=true" -var "enable_interface_endpoints=false"
```

Mientras estén eliminados, una auditoría no puede completarse: la Lambda no
llega a Secrets Manager ni a SNS. Para reanudar, el mismo comando sin
`enable_interface_endpoints`. Las instancias del laboratorio se pausan aparte
([README del laboratorio](../fortigate-lab/README.md#pausar-sin-destruir)).

## Variables

| Variable | Valor por defecto | Uso |
|---|---|---|
| `peer_account_id` | (obligatoria) | Id de la cuenta de laboratorio |
| `peer_vpc_id` | (obligatoria) | Id de la VPC del laboratorio |
| `peer_vpc_cidr` | `10.60.0.0/16` | Bloque de la VPC del laboratorio |
| `peering_accepted` | `false` | Crea la ruta hacia el laboratorio |
| `enable_interface_endpoints` | `true` | Crea los dos puntos de enlace con costo por hora |
| `fortigate_cidr` | `10.60.0.10/32` | Único destino del laboratorio permitido |
| `vpc_cidr` | `10.61.0.0/24` | Bloque de esta VPC |
| `aws_profile` | `pps-tesis` | Perfil de AWS CLI de la cuenta del pipeline |
| `aws_region` | `us-east-1` | Región |
| `availability_zone` | primera disponible | Zona de disponibilidad |
| `name_prefix` | `pg-exec` | Prefijo de los nombres de los recursos |

El estado de Terraform queda en `terraform.tfstate`, en esta carpeta. Git lo
ignora. Contiene el id de la cuenta de laboratorio: no copiarlo ni compartirlo.

## Desarmar todo

El orden importa: la Lambda tiene que salir de la red antes de borrar la red.

1. **Pipeline**: aplicar sin `executor_subnet_ids` ni
   `executor_security_group_ids` (o con las dos listas vacías), y con el
   `fortigate_host` que corresponda de ahí en más. La Lambda vuelve a correr
   fuera de la VPC.
2. **Esperar** a que AWS libere las interfaces de red de la Lambda. Puede
   tardar bastante, desde minutos hasta más de media hora. Comprobar que no
   quede ninguna:

   ```powershell
   aws ec2 describe-network-interfaces --filters Name=group-id,Values=<sg-...> `
     --profile pps-tesis --region us-east-1 --query "NetworkInterfaces[].NetworkInterfaceId"
   ```

   Debe devolver `[]`. Si se destruye antes, `terraform destroy` queda
   esperando y puede fallar por tiempo; en ese caso, esperar y repetirlo.
3. **Esta red**: en `infrastructure/executor-network/`, con las variables del
   paso 1 definidas:

   ```powershell
   terraform destroy
   ```

   Elimina también el emparejamiento.
4. **Laboratorio**: destruirlo
   ([Destruir](../fortigate-lab/README.md#destruir)) o, si se va a seguir
   usando, aplicarlo sin `peer_cidrs` ni `peering_connection_id` para quitar la
   ruta y la regla de entrada. En ese caso, borrar a mano la entrada 9 de los
   orígenes de confianza de `pps-auditor`.

Comprobar que no quedó nada de este módulo:

```powershell
terraform state list
aws resourcegroupstaggingapi get-resources --tag-filters Key=Component,Values=executor-network `
  --profile pps-tesis --region us-east-1 --query "ResourceTagMappingList[].ResourceARN"
```

El primero no debe listar nada y el segundo debe devolver `[]`. Todos los
recursos llevan las etiquetas `Project=PostureGuard`,
`Component=executor-network` y `ManagedBy=terraform`.

## Verificación

No requiere credenciales ni contacta AWS:

```powershell
$env:TF_DATA_DIR = "C:/Users/<usuario>/.terraform-data/pps-executor-network"
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate
```

Resultado del 2026-11-22 con Terraform 1.15.9 y el proveedor aws 6.73.0:
`Success! The configuration is valid.`

Checkov 3.2.379 sobre esta carpeta, el mismo día: 31 comprobaciones aprobadas y
2 fallidas, aceptadas:

| Comprobación | Recurso | Motivo |
|---|---|---|
| `CKV2_AWS_5` (grupo de seguridad sin uso) | Grupo de seguridad de la Lambda | Lo usa la Lambda ejecutora, que se define en `infrastructure/pipeline/`; Checkov no ve esa relación |
| `CKV2_AWS_11` (registros de flujo de la VPC) | VPC | Costo adicional sin uso en la demostración |

Una validación estática no demuestra que el despliegue funcione.

## Lo que falta comprobar

Se comprueba recién al aplicar y ejecutar una auditoría:

- Que el emparejamiento entre las dos cuentas se solicita, se acepta y queda
  `active` con estos recursos.
- Que la Lambda, dentro de la subred, llega a S3, Secrets Manager y SNS por los
  puntos de enlace y al FortiGate por la dirección privada.
- Que el FortiGate responde en `port1` a pedidos que llegan desde
  `10.61.0.0/24` una vez agregado el origen de confianza. La sintaxis del
  paso 4 es la misma de la configuración inicial del laboratorio
  (`bootstrap/fortigate.conf.tftpl`); no se ejecutó en el equipo.
- El bloque de PowerShell del paso 5: el tratamiento de las comillas depende de
  la versión de PowerShell y no se ejecutó. El punto 3 de ese paso detecta un
  valor mal guardado.
- Los costos de la tabla y el tiempo que tarda AWS en liberar las interfaces de
  red de la Lambda.

## Archivos

```text
versions.tf      Versiones de Terraform y del proveedor
provider.tf      Perfil, región y etiquetas por defecto
variables.tf     Variables y sus validaciones
main.tf          VPC, subred, emparejamiento, puntos de enlace y grupos de seguridad
outputs.tf       Salidas para el pipeline y para el laboratorio
```
