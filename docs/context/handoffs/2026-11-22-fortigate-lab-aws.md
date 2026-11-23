# Laboratorio FortiGate desechable en AWS para la demostración

- Fecha e identificador: 2026-11-22, fortigate-lab-aws.
- Estado: Terraform reescrito, validado en forma estática y documentado.
  **No se aplicó en AWS**: no se ejecutó `plan`, `apply` ni `destroy`, ni
  ningún comando de AWS. Nada fue comprobado contra un equipo en
  funcionamiento.
- Rama: `feature/fortigate-lab-aws`, creada desde `master` en `19acf70`, con el
  árbol limpio.
- Commits propios: `0727679` (infraestructura) y un commit documental
  posterior.
- Revisión del desarrollador y merge: pendientes. Push: no realizado.
- Actualización posterior (2026-11-22): el laboratorio se aplicó ese mismo día
  en la cuenta de laboratorio, región `us-east-1`. `terraform plan` informó 37
  recursos a crear y ninguno a modificar o destruir; `terraform apply` creó los
  37. Comprobado desde la estación autorizada: la página de administración
  respondió HTTP 200 por HTTPS y la página de demostración (puerto 8080,
  reenviada al host Ubuntu) respondió HTTP 200, lo que indica que al menos esa
  parte de la configuración inicial se cargó. Sin comprobar todavía: el resto
  de la configuración inicial, el primer inicio de sesión, la generación del
  token y una auditoría de PostureGuard contra el equipo. La suscripción de
  Marketplace ya existía en la cuenta; la tarifa del acuerdo para `t2.small` es
  USD 0,36 por hora.

## Objetivo y aceptación

La demostración de la tesis se hará contra un FortiGate de laboratorio en AWS
(decisión de los autores del 2026-11-22, ver [status.md](../status.md)). Se
pidió reescribir `infrastructure/fortigate-lab/` para que cree un laboratorio
desechable:

- Un FortiGate-VM bajo demanda, FortiOS 7.6.8, y un host Ubuntu detrás.
- Una VPC con subredes `wan`, `lan` y `dmz` en `us-east-1`, en una cuenta
  separada (perfil `lab-fortigate-pfg`).
- Sin entrada desde `0.0.0.0/0`: solo desde la variable obligatoria
  `admin_cidrs`.
- Configuración inicial del FortiGate con contenido realista y debilidades
  deliberadas documentadas.
- Eliminación completa con un solo `terraform destroy`.
- Documentación de creación, primer ingreso, token, auditoría, pausa y
  destrucción.

## Restricciones y autorizaciones

- Sin `terraform plan`, `apply` ni `destroy`, y sin llamadas a AWS. El
  responsable de la cuenta los ejecuta después de revisar este trabajo.
- Sin lectura de archivos `.env`, `*.tfvars` ni de estado.
- Sin direcciones reales, id de cuenta, contraseñas ni tokens en archivos con
  seguimiento. El valor de `admin_cidrs` se pasa por variable de entorno.
- Commits locales en la rama propia; sin push ni merge.

## Cambios

Preexistentes: ninguno; el árbol estaba limpio.

Propios, todos en `infrastructure/fortigate-lab/` salvo la documentación:

- Eliminados `main.tf` e `iam.tf`. El módulo anterior creaba una subred pública
  en `sa-east-1`, un grupo de seguridad con el puerto 443 abierto a
  `0.0.0.0/0`, una instancia `c5.large` con la imagen más reciente sin fijar
  versión, y un rol de instancia con la política administrada `ReadOnlyAccess`
  para el Fabric Connector. Ese rol daba al FortiGate lectura de toda la cuenta
  sin que la demostración lo necesite; se quitó junto con su perfil.
- Nuevos `versions.tf`, `variables.tf`, `network.tf`, `security.tf`,
  `fortigate.tf`, `ubuntu.tf`, `bootstrap/fortigate.conf.tftpl`,
  `bootstrap/ubuntu-cloud-config.yaml` y `.gitattributes`. Reescritos
  `provider.tf`, `outputs.tf` y `README.md`.
- `.terraform.lock.hcl`: se conserva aws 6.44.0 y se agregan random 3.9.1 y
  cloudinit 2.4.1.
- `.gitignore` de la carpeta: sin cambios. Cubre `*.tfstate`, `*.tfstate.*`,
  `.terraform/` y `*.tfvars`, y no ignora `.terraform.lock.hcl`.

## Decisiones y fuentes

- **Interfaces conectadas en el lanzamiento.** Las tres interfaces se declaran
  con bloques `network_interface` de la instancia y no con conexiones
  posteriores, para que `port2` y `port3` existan cuando FortiOS aplica la
  configuración inicial.
- **Formato de la configuración inicial**: MIME con una parte
  `text/x-shellscript`, generado con el proveedor `cloudinit`, igual que la
  plantilla oficial de Fortinet (`fortinet/fortigate-terraform-deploy`,
  `aws/7.6/single`). Esa plantilla usa dos partes; acá hay una sola.
- **Sin cambios posteriores sobre el equipo.** La instancia ignora los cambios
  de `user_data` y `ami`; un cambio se aplica con
  `terraform apply -replace=aws_instance.fortigate`.
- **Discos**: el volumen raíz y los volúmenes adicionales de la imagen se
  declaran cifrados y gp3. Los adicionales se toman de la propia imagen, sin
  suponer el nombre del dispositivo.
- **IMDSv2 obligatorio.** FortiGate-VM en AWS lo usa desde FortiOS 6.4.3, según
  la documentación de Fortinet.
- **Longitud mínima de contraseña**: la referencia de la CLI de 7.6.8 fija el
  rango de `minimum-length` en 12 a 128. La política débil del laboratorio no
  puede bajar de 12; la debilidad queda en la falta de complejidad y de
  vencimiento.
- **`admin_cidrs`**: además de `0.0.0.0/0`, se rechaza cualquier bloque más
  amplio que `/16`, para que no se pueda rodear la validación con dos bloques
  `/1`.
- **Grupo de seguridad por defecto de la VPC** sin reglas.
- Fuentes: referencia de la CLI de FortiOS 7.6.8 (bloques `config` usados),
  guía de administración de FortiGate en AWS 7.6 y la plantilla de Fortinet
  citada. Lo que no se pudo confirmar está en
  [el README del laboratorio](../../../infrastructure/fortigate-lab/README.md#lo-que-falta-comprobar).

## Skills

`pps-terraform` (lectura de su `SKILL.md` y aplicación de sus pasos de
verificación).

## TDD y verificaciones

Cambio declarativo, sin comportamiento ejecutable en el repositorio: se
definieron comprobaciones de formato, validación y análisis estático.

Ejecutado (Windows, Terraform 1.15.9, `TF_DATA_DIR` fuera del árbol):

- `terraform fmt -check -recursive`: sin diferencias.
- `terraform init -backend=false -input=false`: correcto.
- `terraform validate`: `Success! The configuration is valid.`, sin avisos.
- Plantilla del FortiGate renderizada con valores de ejemplo en un directorio
  temporal, sin proveedores: 484 líneas, 10,9 KB (el límite del *user-data* es
  16 KB y la instancia tiene una precondición que lo comprueba).
- Checkov 3.2.379: 74 aprobadas y 8 fallidas, justificadas en el README.

No ejecutado: `terraform plan`, `apply` y `destroy`; cualquier comando de AWS;
las suites de `audit-engine`, `local-api` y `gui` (no se modificaron).

## Pendientes y próximo paso

1. Revisión del desarrollador.
2. Aceptar la suscripción del Marketplace en la cuenta de laboratorio y
   ejecutar `terraform plan` y `apply` según
   [el README](../../../infrastructure/fortigate-lab/README.md#crear-el-laboratorio).
3. En el primer arranque, comprobar la lista de
   [lo que falta comprobar](../../../infrastructure/fortigate-lab/README.md#lo-que-falta-comprobar)
   y corregir la plantilla si algún comando fue rechazado.
4. Generar el token, ejecutar el diagnóstico de forma y una auditoría con el
   script local, y contrastar los hallazgos con la tabla de debilidades.
5. Fase posterior, no iniciada: emparejamiento de VPC con la cuenta de
   PostureGuard y Lambda ejecutora dentro de una VPC.
6. Decisión de merge.
