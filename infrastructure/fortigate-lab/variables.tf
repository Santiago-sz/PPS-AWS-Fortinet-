# -----------------------------------------------------------------------------
# Cuenta y región
# -----------------------------------------------------------------------------

variable "aws_profile" {
  description = "Perfil de AWS CLI de la cuenta de laboratorio."
  type        = string
  default     = "lab-fortigate-pfg"
}

variable "aws_region" {
  description = "Región donde se crea el laboratorio. Debe ser la misma del pipeline para la conexión privada posterior."
  type        = string
  default     = "us-east-1"
}

variable "availability_zone" {
  description = "Zona de disponibilidad única del laboratorio. Con null se usa la primera disponible de la región."
  type        = string
  default     = null
}

variable "name_prefix" {
  description = "Prefijo de los nombres de los recursos."
  type        = string
  default     = "pg-lab"
}

# -----------------------------------------------------------------------------
# Red
# -----------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "Bloque de la VPC. Debe ser /16: las subredes wan, lan y dmz son los tres primeros /24."
  type        = string
  default     = "10.60.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0)) && endswith(var.vpc_cidr, "/16")
    error_message = "vpc_cidr debe ser un bloque IPv4 /16 válido, por ejemplo 10.60.0.0/16."
  }
}

# -----------------------------------------------------------------------------
# Orígenes autorizados
# -----------------------------------------------------------------------------

variable "admin_cidrs" {
  description = <<-EOT
    Direcciones públicas autorizadas a llegar a la interfaz WAN del FortiGate
    por TCP 443 (interfaz web y REST API), 22 y 8080 (reenvío de demostración).
    Sin valor por defecto a propósito: es un dato privado y no se escribe en
    ningún archivo con seguimiento. Pasarlo con TF_VAR_admin_cidrs o -var.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.admin_cidrs) >= 1 && length(var.admin_cidrs) <= 8
    error_message = "admin_cidrs debe tener entre 1 y 8 bloques."
  }

  validation {
    condition = alltrue([
      for c in var.admin_cidrs :
      can(cidrhost(c, 0)) && can(regex("^[0-9.]+/[0-9]+$", c))
    ])
    error_message = "Cada elemento de admin_cidrs debe ser un bloque IPv4 en notación CIDR, por ejemplo 198.51.100.7/32."
  }

  validation {
    condition = alltrue([
      for c in var.admin_cidrs :
      c != "0.0.0.0/0" && try(tonumber(split("/", c)[1]), 0) >= 16
    ])
    error_message = "admin_cidrs no admite 0.0.0.0/0 ni bloques más amplios que /16: el laboratorio no se expone a Internet."
  }
}

variable "peer_cidrs" {
  description = "Bloques privados de una VPC emparejada (fase posterior) autorizados a llegar al FortiGate por TCP 443."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.peer_cidrs) <= 2
    error_message = "peer_cidrs admite hasta 2 bloques."
  }

  validation {
    condition = alltrue([
      for c in var.peer_cidrs :
      can(cidrhost(c, 0)) && can(regex("^[0-9.]+/[0-9]+$", c)) && c != "0.0.0.0/0" && try(tonumber(split("/", c)[1]), 0) >= 16
    ])
    error_message = "Cada elemento de peer_cidrs debe ser un bloque IPv4 en notación CIDR, distinto de 0.0.0.0/0 y no más amplio que /16."
  }
}

# -----------------------------------------------------------------------------
# FortiGate
# -----------------------------------------------------------------------------

variable "fortios_version" {
  description = "Versión de FortiOS de la imagen bajo demanda del Marketplace. Fija la imagen: se busca por este texto en el nombre."
  type        = string
  default     = "7.6.8"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.fortios_version))
    error_message = "fortios_version debe tener la forma mayor.menor.parche, por ejemplo 7.6.8."
  }
}

variable "fortigate_product_code" {
  description = "Código de producto del Marketplace de FortiGate-VM bajo demanda (PAYG)."
  type        = string
  default     = "2wqkpek696qhdeo7lbbjncqli"
}

variable "fortigate_instance_type" {
  description = "Tipo de instancia del FortiGate. Debe admitir al menos 3 interfaces de red (t2.small admite exactamente 3)."
  type        = string
  default     = "t2.small"
}

variable "fortigate_hostname" {
  description = "Nombre de host que la configuración inicial asigna al FortiGate."
  type        = string
  default     = "pg-lab-fgt01"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]{1,35}$", var.fortigate_hostname))
    error_message = "fortigate_hostname admite hasta 35 letras, números o guiones."
  }
}

variable "api_user_name" {
  description = "Nombre del usuario de REST API de solo lectura que usa PostureGuard."
  type        = string
  default     = "pps-auditor"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]{1,35}$", var.api_user_name))
    error_message = "api_user_name admite hasta 35 letras, números o guiones."
  }
}

# -----------------------------------------------------------------------------
# Host Ubuntu
# -----------------------------------------------------------------------------

variable "ubuntu_instance_type" {
  description = "Tipo de instancia del host Ubuntu detrás del FortiGate."
  type        = string
  default     = "t3.micro"
}
