# Terraform — FortiGate en AWS (Sandbox)

Despliegue automatizado de una instancia **FortiGate VM** en AWS usando Terraform. Pensado como entorno de pruebas aislado para el framework de seguridad del proyecto PPS.

## ¿Qué despliega?

```
VPC (10.0.0.0/16)
└── Subnet pública (10.0.1.0/24)
    ├── Internet Gateway
    ├── Route Table (0.0.0.0/0 → IGW)
    ├── Security Group (ingreso HTTPS 443)
    └── EC2 FortiGate VM64 (c5.large)
        └── IAM Role — Fabric Connector (solo lectura)
```

- **VPC aislada** (`UNNE-Sandbox-VPC`) para contener el entorno de pruebas
- **FortiGate VM64 On-Demand** — última AMI disponible en AWS Marketplace, región `sa-east-1`
- **Security Group** que permite ingreso por HTTPS (443) para acceso a la consola de administración
- **IAM Role** con política `ReadOnlyAccess` para el Fabric Connector de Fortinet, que permite al FortiGate descubrir y auditar la infraestructura de AWS

## Requisitos previos

- [Terraform](https://developer.hashicorp.com/terraform/downloads) >= 1.0
- AWS CLI configurado (`aws configure`)
- Suscripción activa a **FortiGate-VM64-AWSONDEMAND** en AWS Marketplace (región `sa-east-1`)

## Uso

```bash
# 1. Inicializar providers
terraform init

# 2. Ver qué se va a crear
terraform plan

# 3. Aplicar
terraform apply
```

Al finalizar, Terraform imprime la IP pública y el ID de la instancia:

```
fortigate_public_ip  = "x.x.x.x"
fortigate_instance_id = "i-xxxxxxxxxxxxxxxxx"
```

Accedé a la consola de FortiGate desde el navegador: `https://<fortigate_public_ip>`

## Destruir el entorno

```bash
terraform destroy
```

## Estructura del proyecto

```
.
├── provider.tf       # Región AWS (sa-east-1)
├── main.tf           # VPC, subnet, IGW, security group e instancia FortiGate
├── iam.tf            # IAM Role y profile para el Fabric Connector
├── outputs.tf        # IP pública e ID de la instancia
└── .gitignore        # Excluye credenciales y estado de Terraform
```

## Seguridad

- Las credenciales de AWS **nunca** se almacenan en el código. Usá `aws configure` o variables de entorno.
- Los archivos `.tfstate` están en `.gitignore` — nunca commitear estado de Terraform.
- El Security Group actual permite HTTPS desde cualquier IP (`0.0.0.0/0`). En producción, restringir al rango de IPs de administración.
