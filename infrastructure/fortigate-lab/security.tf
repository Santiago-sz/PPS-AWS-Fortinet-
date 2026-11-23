# -----------------------------------------------------------------------------
# Grupos de seguridad. Ninguna regla de entrada usa 0.0.0.0/0.
# -----------------------------------------------------------------------------

# Interfaz WAN del FortiGate: solo los orígenes de admin_cidrs (443, 22, 8080)
# y, en la fase de conexión privada, los de peer_cidrs (443).
resource "aws_security_group" "fortigate_wan" {
  name        = "${var.name_prefix}-fgt-wan"
  description = "FortiGate WAN: acceso solo desde origenes autorizados"
  vpc_id      = aws_vpc.lab.id

  tags = { Name = "${var.name_prefix}-fgt-wan" }
}

locals {
  admin_ports = {
    https = { port = 443, description = "Interfaz web y REST API" }
    ssh   = { port = 22, description = "CLI por SSH" }
    demo  = { port = 8080, description = "Reenvio de demostracion al host Ubuntu" }
  }

  admin_ingress = {
    for pair in setproduct(keys(local.admin_ports), var.admin_cidrs) :
    "${pair[0]}-${pair[1]}" => {
      port        = local.admin_ports[pair[0]].port
      description = local.admin_ports[pair[0]].description
      cidr        = pair[1]
    }
  }
}

resource "aws_vpc_security_group_ingress_rule" "fortigate_wan_admin" {
  for_each = local.admin_ingress

  security_group_id = aws_security_group.fortigate_wan.id
  description       = each.value.description
  cidr_ipv4         = each.value.cidr
  ip_protocol       = "tcp"
  from_port         = each.value.port
  to_port           = each.value.port
}

resource "aws_vpc_security_group_ingress_rule" "fortigate_wan_peer" {
  for_each = toset(var.peer_cidrs)

  security_group_id = aws_security_group.fortigate_wan.id
  description       = "REST API desde la VPC emparejada"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "fortigate_wan_all" {
  security_group_id = aws_security_group.fortigate_wan.id
  description       = "Salida del FortiGate (FortiGuard, DNS, NTP y trafico de lan y dmz)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Interfaces LAN y DMZ del FortiGate: solo tráfico originado dentro de la VPC.
resource "aws_security_group" "fortigate_internal" {
  name        = "${var.name_prefix}-fgt-internal"
  description = "FortiGate LAN y DMZ: solo trafico de la VPC"
  vpc_id      = aws_vpc.lab.id

  tags = { Name = "${var.name_prefix}-fgt-internal" }
}

resource "aws_vpc_security_group_ingress_rule" "fortigate_internal_vpc" {
  security_group_id = aws_security_group.fortigate_internal.id
  description       = "Trafico de la VPC hacia el FortiGate"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "fortigate_internal_all" {
  security_group_id = aws_security_group.fortigate_internal.id
  description       = "Trafico reenviado por el FortiGate"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Host Ubuntu: solo tráfico originado dentro de la VPC.
resource "aws_security_group" "ubuntu" {
  name        = "${var.name_prefix}-ubuntu"
  description = "Host Ubuntu: solo trafico de la VPC"
  vpc_id      = aws_vpc.lab.id

  tags = { Name = "${var.name_prefix}-ubuntu" }
}

resource "aws_vpc_security_group_ingress_rule" "ubuntu_vpc" {
  security_group_id = aws_security_group.ubuntu.id
  description       = "Trafico de la VPC hacia el host"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "ubuntu_all" {
  security_group_id = aws_security_group.ubuntu.id
  description       = "Salida del host, siempre a traves del FortiGate"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Grupo de seguridad por defecto de la VPC: sin reglas, para que nada lo use
# por omisión.
resource "aws_default_security_group" "lab" {
  vpc_id = aws_vpc.lab.id

  tags = { Name = "${var.name_prefix}-default-sin-uso" }
}
