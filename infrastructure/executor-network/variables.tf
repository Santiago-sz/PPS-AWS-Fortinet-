# -----------------------------------------------------------------------------
# Cuenta y región
# -----------------------------------------------------------------------------

variable "aws_profile" {
  description = "Perfil de AWS CLI de la cuenta del pipeline de PostureGuard."
  type        = string
  default     = "pps-tesis"
}

variable "aws_region" {
  description = "Región de la red. Debe ser la misma del pipeline y del laboratorio."
  type        = string
  default     = "us-east-1"
}

variable "availability_zone" {
  description = "Zona de disponibilidad única de la subred. Con null se usa la primera disponible de la región."
  type        = string
  default     = null
}

variable "name_prefix" {
  description = "Prefijo de los nombres de los recursos."
  type        = string
  default     = "pg-exec"
}

# -----------------------------------------------------------------------------
# Red propia
# -----------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "Bloque de la VPC de la Lambda ejecutora. No debe superponerse con el del laboratorio."
  type        = string
  default     = "10.61.0.0/24"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0)) && can(regex("^[0-9.]+/(1[6-9]|2[0-6])$", var.vpc_cidr))
    error_message = "vpc_cidr debe ser un bloque IPv4 válido entre /16 y /26, por ejemplo 10.61.0.0/24."
  }
}

variable "enable_interface_endpoints" {
  description = "Crea los puntos de enlace de interfaz de Secrets Manager y SNS, que se cobran por hora. Con false no hay costo por hora, pero la Lambda ejecutora no puede completar una auditoría dentro de esta red."
  type        = bool
  default     = true
}

# -----------------------------------------------------------------------------
# Laboratorio (otra cuenta)
# -----------------------------------------------------------------------------

variable "fortigate_cidr" {
  description = "Dirección privada de la interfaz WAN del FortiGate de laboratorio, como bloque /32. Es el único destino del laboratorio que admite el grupo de seguridad."
  type        = string
  default     = "10.60.0.10/32"

  validation {
    condition     = can(cidrhost(var.fortigate_cidr, 0)) && endswith(var.fortigate_cidr, "/32")
    error_message = "fortigate_cidr debe ser una dirección IPv4 con máscara /32, por ejemplo 10.60.0.10/32."
  }
}

variable "peer_account_id" {
  description = "Id de la cuenta de AWS del laboratorio. Sin valor por defecto a propósito: no se escribe en ningún archivo con seguimiento. Pasarlo con -var o TF_VAR_peer_account_id."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.peer_account_id))
    error_message = "peer_account_id debe tener 12 dígitos."
  }
}

variable "peer_vpc_id" {
  description = "Id de la VPC del laboratorio (salida vpc_id de infrastructure/fortigate-lab)."
  type        = string

  validation {
    condition     = can(regex("^vpc-[0-9a-f]{8,17}$", var.peer_vpc_id))
    error_message = "peer_vpc_id debe tener la forma vpc-0123456789abcdef0."
  }
}

variable "peer_vpc_cidr" {
  description = "Bloque de la VPC del laboratorio (salida vpc_cidr de infrastructure/fortigate-lab)."
  type        = string
  default     = "10.60.0.0/16"

  validation {
    condition     = can(cidrhost(var.peer_vpc_cidr, 0)) && can(regex("^[0-9.]+/[0-9]+$", var.peer_vpc_cidr)) && var.peer_vpc_cidr != "0.0.0.0/0"
    error_message = "peer_vpc_cidr debe ser un bloque IPv4 en notación CIDR, distinto de 0.0.0.0/0."
  }
}

variable "peering_accepted" {
  description = "Poner true después de que el laboratorio aceptó el emparejamiento. Recién entonces se crea la ruta hacia el laboratorio, para no depender de una ruta por un emparejamiento que todavía no está activo."
  type        = bool
  default     = false
}
