# Ejecución local del executor a través de una VPN de usuario

Fecha: 2026-11-21. Guía de la **primera prueba** contra un FortiGate real.

## Cuándo usar este camino

El primer equipo real disponible solo es alcanzable desde una estación Windows
conectada con una VPN de usuario (FortiClient). La Lambda `audit_executor` no
tiene ruta hacia él. Para esa prueba, la generación sigue en AWS y la etapa de
ejecución corre en la estación con
[`audit-engine/scripts/run_executor_local.py`](../../audit-engine/scripts/run_executor_local.py).

Este camino es exclusivamente para la primera prueba. La arquitectura objetivo
no cambia: VPN Site-to-Site IPsec con el executor dentro de una VPC, opción (a)
de [la conexión del FortiGate](../base/06-conexion-fortigate.md).

El script aplica el mismo orden de controles que la Lambda y reutiliza sus
módulos sin modificarlos:

1. Lee `artifacts/<run_id>/manifest.json` y el script desde S3 (solo lectura).
2. Verifica el SHA-256 del script contra el manifest.
3. Vuelve a validar el script desde cero con `script_validator.validate`.
4. Comprueba la conectividad con una lectura (`system_global`).
5. Ejecuta el script en el mismo sandbox, con el mismo toolkit y presupuesto.

Diferencias deliberadas con la Lambda:

| Aspecto | Lambda `audit_executor` | Ejecución local |
|---|---|---|
| Token | Secrets Manager | Variable de entorno `FORTIGATE_TOKEN` |
| Reporte | `reports/<run_id>/` en S3 y aviso por SNS | Solo en un directorio local |
| Conectividad fallida | Reporte `completed` con hallazgos `indeterminate` | Aborta antes de ejecutar, código de salida 3 |
| Respaldo de tiempo por señal | Activo (Linux) | Inactivo en Windows; el script lo advierte |

El reporte no se sube a S3 a propósito: `reports/<run_id>/report.json` marca la
corrida como terminada y `pps-api aws approve` la rechazaría después.

El script solo hace lecturas `GET`. No escribe en el FortiGate, en S3, en SNS
ni en Secrets Manager, y no tiene opción para publicar el reporte.

## 1. Preparar el FortiGate

Lo realiza quien administra el equipo. Sintaxis de referencia para FortiOS 7.x;
comprobarla contra la versión instalada.

1. Crear el perfil de solo lectura `pps-readonly` según
   [la sección 1.1 de la conexión](../base/06-conexion-fortigate.md). Todos los
   grupos en `read`; ninguno en `read-write`.
2. Crear el usuario de API REST (en la interfaz web: *System > Administrators >
   Create New > REST API Admin*) con ese perfil.
3. Configurar el *trusted host* con la dirección IP que la VPN asigna a la
   estación, con máscara `/32`. Esa dirección es la del adaptador de la VPN, no
   la de la red local ni la IP pública. Con la VPN conectada:

   ```powershell
   Get-NetIPAddress -AddressFamily IPv4 | Format-Table InterfaceAlias, IPAddress
   ```

   Si la VPN entrega una dirección distinta en cada conexión, usar el rango más
   acotado posible del conjunto de direcciones de la VPN.

   ```text
   config system api-user
       edit "pps-auditor"
           set accprofile "pps-readonly"
           set vdom "root"
           config trusthost
               edit 1
                   set type ipv4-trusthost
                   set ipv4-trusthost 192.0.2.10 255.255.255.255
               next
           end
       next
   end
   ```

   `192.0.2.10` es un ejemplo: reemplazarlo por la dirección asignada.
4. Generar el token (`execute api-user generate-key pps-auditor`, o el botón de
   la interfaz web). Se muestra una sola vez.

La interfaz por la que llega el tráfico de la VPN debe permitir el acceso
administrativo HTTPS, y debe existir una política que permita ese tráfico.

## 2. Tratamiento del token

- No pegarlo en conversaciones, tickets, correos, documentos ni commits.
- No guardarlo en archivos del repositorio ni en archivos `.env`.
- No pasarlo como argumento de un comando: quedaría en el historial de la
  consola. El script no acepta el token por argumento.
- Cargarlo solo en la sesión de PowerShell que ejecuta la prueba:

  ```powershell
  $secure = Read-Host -AsSecureString "Token FortiGate"
  $env:FORTIGATE_TOKEN = [System.Net.NetworkCredential]::new("", $secure).Password
  Remove-Variable secure
  ```

- Al terminar: `Remove-Item Env:FORTIGATE_TOKEN` o cerrar la consola. Si el
  token pudo quedar expuesto, regenerarlo en el equipo.

El script no imprime el token, no lo registra y lo reemplaza por `[REDACTED]`
si aparece en un mensaje de registro o en el contenido del reporte.

## 3. Variables de entorno

En la misma sesión de PowerShell, con la VPN conectada:

```powershell
$env:AWS_PROFILE = "<AWS_PROFILE>"
$env:AWS_DEFAULT_REGION = "us-east-1"
$env:S3_BUCKET = "<BUCKET_DE_REPORTES>"
$env:FORTIGATE_HOST = "192.0.2.10"        # o 192.0.2.10:8443 si el puerto no es 443
$env:FORTIGATE_VERIFY_SSL = "false"       # solo con certificado autofirmado
```

| Variable | Obligatoria | Uso |
|---|---|---|
| `S3_BUCKET` | Sí (o `--bucket`) | Bucket de reportes, donde están `artifacts/` |
| `FORTIGATE_HOST` | Sí | Host o `host:puerto`, sin `https://` ni ruta |
| `FORTIGATE_TOKEN` | Sí | Token del usuario de API (sección 2) |
| `FORTIGATE_VERIFY_SSL` | No | `true` por defecto. `false` solo en laboratorio |
| `SANDBOX_WALL_CLOCK_SECONDS`, `SANDBOX_MAX_FGT_CALLS` | No | Presupuesto del sandbox, igual que en la Lambda |
| `LOG_LEVEL` | No | `INFO` por defecto |

Las credenciales de AWS se resuelven con la cadena habitual de boto3. El perfil
solo necesita `s3:GetObject` sobre `artifacts/*` del bucket de reportes.

## 4. Comprobación manual de conectividad

Antes de ejecutar el script, con las variables ya cargadas:

```powershell
curl.exe -k -H "Authorization: Bearer $env:FORTIGATE_TOKEN" "https://$env:FORTIGATE_HOST/api/v2/cmdb/system/global"
```

Usar `curl.exe` y no `curl`, que en Windows PowerShell 5.1 es un alias de otro
comando. Quitar `-k` si el certificado es de una CA confiable. La respuesta
esperada trae `"http_status": 200` y un campo `results`. El comando no muestra
el token, pero la respuesta contiene configuración del equipo: no compartirla.

## 5. Obtener el `run_id`

Subir la normativa por el camino habitual (aplicación de escritorio y
`pps-api aws dispatch`). La generación ocurre en AWS y deja el script y el
manifest en `artifacts/<run_id>/`.

```powershell
.\.venv-gui\Scripts\python local-api/launch.py aws list-pending
```

No ejecutar `aws approve` para esa corrida: invocaría a la Lambda, que no
alcanza el equipo.

Si el generador está desplegado con `auto_execute = true` (valor por defecto de
la variable de Terraform; el valor desplegado no fue comprobado al escribir esta
guía), invoca a la Lambda al terminar. Esa ejecución deja en S3 un reporte con
todos los hallazgos `indeterminate`, que debe ignorarse. La ejecución local
sigue siendo posible porque no depende de ese reporte. Para evitarlo, desplegar
con `auto_execute = false`; ese cambio requiere autorización del responsable de
la cuenta.

## 6. Ejecutar

```powershell
cd <RAIZ_DEL_REPOSITORIO>\audit-engine
..\.venv\Scripts\python.exe scripts\run_executor_local.py <run_id>
```

Opciones: `--bucket <nombre>` reemplaza a `S3_BUCKET`; `--output-dir <ruta>`
cambia el directorio de salida.

## 7. Resultado

El reporte queda en
`audit-engine\local-runs\<run_id>\<fecha-hora-UTC>\report.json` y `report.md`.
Cada ejecución crea un directorio nuevo; no se sobrescriben. El directorio
`local-runs/` está ignorado por Git: los reportes contienen evidencia de la
configuración real del equipo y no deben incorporarse al repositorio.

El reporte local lleva el bloque `execution` (`mode: local`,
`published: false`) en el JSON y una nota al final del Markdown.

| Código de salida | Significado |
|---|---|
| 0 | Auditoría completa; reporte escrito |
| 1 | Reporte escrito, auditoría incompleta: hash distinto, script rechazado por el validador, error del script o presupuesto del sandbox agotado (`truncated`) |
| 2 | Error de configuración o de entrada (variables, `run_id`, lectura de S3). No se ejecutó nada |
| 3 | Falló la comprobación de conectividad. No se ejecutó nada ni se escribió reporte |

Con código 0, revisar igualmente los hallazgos `indeterminate`: un endpoint
puntual puede fallar (por ejemplo, un `403` sobre un árbol que el perfil no
puede leer) aunque la conectividad general funcione.

## 8. Si falla la comprobación de conectividad

Las líneas de registro anteriores al mensaje de error muestran el código HTTP o
el error de red.

| Síntoma en el registro | Causa probable | Qué revisar |
|---|---|---|
| Tiempo de espera agotado o conexión rechazada | VPN desconectada o sin ruta al equipo | Estado de FortiClient; repetir la sección 4 |
| `HTTP 401` | Token inválido o regenerado, o *trusted host* que no incluye la IP asignada por la VPN | Sección 1, paso 3; volver a cargar el token |
| `HTTP 403` | Perfil sin lectura sobre ese árbol, o *trusted host* | Perfil `pps-readonly`; *trusted host* |
| Conexión rechazada en el puerto 443 | Puerto de administración distinto | `FORTIGATE_HOST` con `host:puerto` |
| `CERTIFICATE_VERIFY_FAILED` | Certificado autofirmado | `FORTIGATE_VERIFY_SSL=false`, solo en laboratorio |

## Límites conocidos

- El reporte local no aparece en la aplicación de escritorio ni en
  `pps-api aws sync`. No se probó importarlo con `import-result`.
- En Windows no existe `signal.setitimer`: el respaldo de tiempo por señal del
  sandbox está inactivo. Siguen vigentes el límite de tiempo y el de cantidad
  de llamadas que se comprueban en cada llamada a `fgt` y `report`.
- El script no fue ejecutado contra un FortiGate real ni contra AWS al escribir
  esta guía; su comportamiento está cubierto por tests con S3 simulado y un
  cliente FortiGate simulado.
