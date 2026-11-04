# 06 — Conexión del FortiGate real

Diagrama: `diagrams/04-conectividad-fortigate.png`.

Estado actual: en la cuenta `656051538542` **no existe** ningún FortiGate ni
VPN. Hay dos VPC: la default (`172.31.0.0/16`) y `vpc-0542264dd516d931e`
(`10.42.0.0/16`). La carpeta `fortigate-sandbox-2026-06-07/` despliega una
FortiGate-VM en **`sa-east-1`** (otra región y otra VPC, `10.0.0.0/16`), por lo
que no es alcanzable por IP privada desde `us-east-1` sin peering inter-región.

El executor solo necesita **HTTPS saliente al puerto 443** del FortiGate y
realiza únicamente `GET` sobre `/api/v2/cmdb/...`. Nunca escribe.

## 1. Preparar el FortiGate (FortiOS 7.x)

Sintaxis de referencia; verificar contra la versión exacta de FortiOS del
equipo (los nombres de grupos del `accprofile` pueden variar entre versiones).

### 1.1 Perfil de acceso de solo lectura

```text
config system accprofile
    edit "pps-readonly"
        set comments "Auditoria PPS - solo lectura"
        set secfabgrp read
        set ftviewgrp read
        set authgrp read
        set sysgrp read
        set netgrp read
        set loggrp read
        set fwgrp read
        set vpngrp read
        set utmgrp read
        set wanoptgrp read
        set wifi read
    next
end
```

Todos los grupos en `read`; ninguno en `read-write`. El catálogo actual solo
consulta `system`, `firewall`, `vpn`, `user`, `ips`, `antivirus` y `webfilter`
(ver §4), pero dejar lectura completa simplifica ampliar el catálogo sin tocar
el equipo.

### 1.2 Usuario de API REST con trusted hosts

```text
config system api-user
    edit "pps-auditor"
        set comments "Token REST usado por la Lambda audit_executor"
        set accprofile "pps-readonly"
        set vdom "root"
        config trusthost
            edit 1
                set type ipv4-trusthost
                set ipv4-trusthost <RED_DE_ORIGEN> <MASCARA>
            next
        end
    next
end
```

`<RED_DE_ORIGEN>` depende de la opción de conectividad (§2): la subred privada
del executor (opción a/b) o la IP de NAT fija (opción c). Sin trusted hosts
el token sirve desde cualquier origen que alcance el puerto 443: no hacerlo.

### 1.3 Generar el token

```text
execute api-user generate-key pps-auditor
```

El token se muestra **una sola vez**. Cargarlo en Secrets Manager
(`02-paso-a-paso-despliegue-y-prueba.md` §7.2):

```powershell
aws secretsmanager put-secret-value --secret-id <fortigate_secret_arn> `
  --secret-string '{"token":"<TOKEN>","host":"<IP_O_HOSTNAME>"}' --region us-east-1 --profile pps-tesis
```

Regenerar la clave invalida la anterior: repetir `put-secret-value`.

### 1.4 HTTPS únicamente

- Administración por HTTPS/443 (`config system global` → `set admin-https-redirect enable`,
  deshabilitar HTTP en las interfaces de gestión: `config system interface` →
  `set allowaccess https ping`).
- Certificado: el cliente verifica TLS por defecto (`FORTIGATE_VERIFY_SSL`
  ausente → `true`). Con certificado autofirmado el executor falla con
  `CERTIFICATE_VERIFY_FAILED`. Opciones: instalar un certificado emitido por
  una CA confiable (recomendado) o, **solo en laboratorio**, inyectar
  `FORTIGATE_VERIFY_SSL="false"` en el bloque `environment` del executor en
  `terraform/lambda.tf` (hoy Terraform no expone esa variable; es un cambio de
  código pendiente).

## 2. Opciones de conectividad

| | (a) FortiGate on-prem + VPN Site-to-Site + executor en VPC | (b) FortiGate-VM en AWS, misma VPC/región | (c) IP pública de gestión restringida por trusted hosts |
|---|---|---|---|
| **Cómo** | VGW/TGW + Customer Gateway en el FortiGate (IPsec), subred privada con ruta hacia la red on-prem; `executor_subnet_ids` + `executor_security_group_ids` en `terraform.tfvars` | Desplegar la VM (base: `fortigate-sandbox-2026-06-07/`, cambiando `provider.tf` a `us-east-1` y la VPC a una existente o con peering); executor en una subred con ruta al puerto de gestión privado de la VM | Exponer 443 de gestión en Internet, trusted hosts = IP(s) de egreso del executor |
| **Terraform del pipeline** | Completar ambas listas (precondición: ambas vacías o ambas con valores); el rol recibe `AWSLambdaVPCAccessExecutionRole`; las subredes necesitan NAT o VPC endpoints para S3, Secrets Manager y SNS porque la Lambda pierde el acceso público implícito | Igual que (a) | Dejar las listas vacías (executor fuera de VPC) |
| **Trusted hosts** | CIDR de la subred privada del executor | CIDR de la subred del executor | Lambda fuera de VPC **no tiene IP de egreso fija**: habría que colocarla en VPC con NAT Gateway (EIP fija) para que el trusted host tenga sentido |
| **Ventajas** | Es el escenario real de la institución; tráfico cifrado extremo a extremo; sin exposición pública | Más simple para la tesis; todo en AWS; IaC reproducible; costo acotado al tiempo de laboratorio | Mínimo esfuerzo de red |
| **Desventajas** | Requiere equipo real, IP pública estática del lado on-prem, coordinación con el área de redes; costo horario de VGW/TGW | La VM FortiGate tiene costo por hora (c5.large + licencia on-demand); el sandbox existente está en `sa-east-1` | **No recomendada**: superficie de gestión expuesta; trusted hosts sin IP fija no protegen; aun con NAT, el 443 público queda visible a Internet |
| **Cuándo** | Despliegue en la institución (PPS II / producción) | Demostración y evaluación de la tesis | Solo pruebas puntuales y temporales |

Para la opción (b) con la VPC `10.42.0.0/16` existente: subred privada para el
executor + SG de egreso `443` hacia el SG de la VM; SG de la VM con ingreso
`443` **solo** desde el SG del executor (no `0.0.0.0/0` como en el sandbox);
VPC endpoints de tipo Gateway para S3 y de tipo Interface para Secrets
Manager y SNS, o un NAT Gateway.

## 3. Verificación desde fuera de AWS

Desde una máquina con acceso al equipo (sustituir valores; `-k` solo si el
certificado es autofirmado):

```bash
curl -k -H "Authorization: Bearer <TOKEN>" https://<host>/api/v2/monitor/system/status
curl -k -H "Authorization: Bearer <TOKEN>" "https://<host>/api/v2/cmdb/system/global"
curl -k -H "Authorization: Bearer <TOKEN>" "https://<host>/api/v2/cmdb/system/admin"
```

Respuestas esperadas: `http_status: 200` y un campo `results`. `401` = token
inválido; `403` = perfil sin permiso sobre ese árbol; timeout = red/trusted
hosts. Una prueba de escritura **no** debe hacerse: el perfil es de solo
lectura y el pipeline nunca la necesita.

Desde AWS, una vez desplegado, la prueba real es la sección 9 de
`02-paso-a-paso-despliegue-y-prueba.md`: en el log del executor, cada
`fgt.get` que no alcanza el equipo deja `No se puede conectar al FortiGate
(https://<host>/api/v2/cmdb/<path>)` y el hallazgo queda `indeterminate`.

## 4. Endpoints que el catálogo lee hoy

`audit-pipeline/lambda/fortigate_client.py::ENDPOINTS` (todos bajo
`https://<host>/api/v2/cmdb/`):

| Path REST | Label usado por `fgt.get()` | Qué permite auditar |
|---|---|---|
| `system/global` | `system_global` | timeout de administración, HTTPS/redirect, puertos de gestión, lockout |
| `system/interface` | `interfaces` | `allowaccess` por interfaz (HTTP/Telnet/SSH), zonas |
| `system/admin` | `admins` | administradores locales, trusted hosts, perfiles, 2FA |
| `system/dns` | `dns` | servidores DNS, DoT/DoH |
| `firewall/policy` | `firewall_policies` | políticas, logging por política, perfiles UTM aplicados |
| `vpn.ipsec/phase1-interface` | `vpn_ipsec` | túneles IPsec, algoritmos, DPD |
| `vpn.ssl/settings` | `vpn_ssl` | SSL-VPN, cifrado, puerto, timeouts |
| `user/local` | `local_users` | usuarios locales, 2FA |
| `ips/sensor` | `ips_sensors` | sensores IPS |
| `antivirus/profile` | `av_profiles` | perfiles antivirus |
| `webfilter/profile` | `webfilter_profiles` | perfiles de filtrado web |
| `system/password-policy` | `password_policy` | longitud mínima, complejidad, expiración, reutilización |
| `system/accprofile` | `admin_profiles` | perfiles de permisos de administración |
| `system/api-user` | `api_users` | usuarios de API REST, trusted hosts, perfil |
| `user/ldap` | `ldap_servers` | servidores LDAP, LDAPS, cuenta de bind |
| `user/radius` | `radius_servers` | servidores RADIUS, protocolo de autenticación |
| `system/ntp` | `ntp` | sincronización horaria, servidores NTP |
| `log.syslogd/setting` | `log_syslogd` | envío de logs a syslog, modo reliable, cifrado |
| `log.fortianalyzer/setting` | `log_fortianalyzer` | envío de logs a FortiAnalyzer, cifrado |
| `log/setting` | `log_settings` | configuración general de logging (política implícita, resolución) |
| `log.memory/setting` | `log_memory` | logging en memoria, severidad mínima |
| `system/ha` | `ha` | alta disponibilidad, modo, heartbeat, cifrado HA |
| `system/settings` | `vdom_settings` | ajustes del VDOM (gui, inspección, timeouts) |
| `system/central-management` | `central_management` | gestión centralizada (FortiManager) |
| `router/static` | `static_routes` | rutas estáticas, gateway por defecto |
| `system/sdwan` | `sdwan` | SD-WAN, miembros, health checks |
| `system/dhcp/server` | `dhcp_servers` | servidores DHCP, rangos, DNS entregado |
| `system/snmp/sysinfo` | `snmp_sysinfo` | SNMP habilitado, contacto, ubicación |
| `system/fortiguard` | `fortiguard` | actualizaciones FortiGuard, protocolo/puerto |
| `firewall/address` | `firewall_addresses` | objetos de dirección usados por políticas |
| `firewall/ssl-ssh-profile` | `ssl_ssh_profiles` | inspección SSL/SSH, certificados |

Las 20 últimas filas son la ampliación del catálogo hecha tras los evals:
todas son lecturas GET sobre `cmdb`, agrupadas en identidad/administración,
registro y tiempo, red y seguridad (ver el comentario en `ENDPOINTS`). El
validador rechaza cualquier `fgt.get("...")` cuyo literal no sea uno de
estos 31 labels (`endpoint_not_in_catalog`), y el prompt de map instruye al
modelo a no inventar controles fuera del catálogo.

## 5. Brecha del catálogo (resuelta)

Las evals (`evals/README.md`) detectaron que las cláusulas de longitud,
complejidad e historial de contraseñas, de NTP y de envío de logs no
producían checks porque faltaban en `ENDPOINTS`. La ampliación de la tabla
anterior (en particular `password_policy`, `ntp`, `log_syslogd`,
`log_fortianalyzer`, `log_settings`) cerró esa brecha: las normativas de
contraseñas y de registro/NTP pasaron de 5 a 9 y de 4 a 8 checks sin tocar
validador ni sandbox. Si en el futuro aparece otra cláusula sin endpoint,
el camino es el mismo: agregar la tupla `(path, label)`, re-grabar las
fixtures de evals (`run_evals.py --mode live --record`) y actualizar
`expected/*.json`.
