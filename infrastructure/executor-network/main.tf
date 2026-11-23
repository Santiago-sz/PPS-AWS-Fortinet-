# -----------------------------------------------------------------------------
# Red: una VPC con una sola subred privada. Sin gateway de Internet ni NAT.
# -----------------------------------------------------------------------------

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  az = coalesce(var.availability_zone, data.aws_availability_zones.available.names[0])

  # Servicios de AWS que la Lambda ejecutora llama y que no tienen punto de
  # enlace gratuito. S3 usa un punto de enlace de tipo gateway, sin costo.
  interface_services = var.enable_interface_endpoints ? toset(["secretsmanager", "sns"]) : toset([])
}

resource "aws_vpc" "executor" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # requerido por el DNS privado de los puntos de enlace

  tags = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_subnet" "private" {
  vpc_id                  = aws_vpc.executor.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 1, 0)
  availability_zone       = local.az
  map_public_ip_on_launch = false

  tags = { Name = "${var.name_prefix}-private" }
}

# Única tabla de rutas: local, S3 por el punto de enlace y, cuando el
# emparejamiento está aceptado, el laboratorio. No hay ruta por defecto.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.executor.id

  tags = { Name = "${var.name_prefix}-rt-private" }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}

# -----------------------------------------------------------------------------
# Emparejamiento de VPC con el laboratorio (otra cuenta, misma región)
# -----------------------------------------------------------------------------

# Esta cuenta lo solicita; el laboratorio lo acepta desde su propio módulo
# (variable peering_connection_id de infrastructure/fortigate-lab).
resource "aws_vpc_peering_connection" "lab" {
  vpc_id        = aws_vpc.executor.id
  peer_vpc_id   = var.peer_vpc_id
  peer_owner_id = var.peer_account_id

  tags = { Name = "${var.name_prefix}-to-lab" }
}

resource "aws_route" "lab" {
  count = var.peering_accepted ? 1 : 0

  route_table_id            = aws_route_table.private.id
  destination_cidr_block    = var.peer_vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.lab.id
}

# -----------------------------------------------------------------------------
# Puntos de enlace hacia los servicios de AWS que usa la Lambda ejecutora
# -----------------------------------------------------------------------------

# S3 (artifacts/* y reports/*): tipo gateway, sin costo.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.executor.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = { Name = "${var.name_prefix}-s3" }
}

# Secrets Manager (token del FortiGate) y SNS (aviso de fin de auditoría):
# tipo interfaz, con costo por hora. El DNS privado hace que el SDK los use
# sin cambios en el código.
resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_services

  vpc_id              = aws_vpc.executor.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private.id]
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${var.name_prefix}-${each.value}" }
}

# -----------------------------------------------------------------------------
# Grupos de seguridad. Ninguna regla usa 0.0.0.0/0.
# -----------------------------------------------------------------------------

# Lambda ejecutora: sin entrada. Salida solo por TCP 443 hacia el FortiGate,
# hacia los puntos de enlace de interfaz y hacia S3.
resource "aws_security_group" "executor" {
  name        = "${var.name_prefix}-lambda"
  description = "Lambda ejecutora: salida HTTPS solo al FortiGate y a los servicios de AWS"
  vpc_id      = aws_vpc.executor.id

  tags = { Name = "${var.name_prefix}-lambda" }
}

resource "aws_vpc_security_group_egress_rule" "executor_fortigate" {
  security_group_id = aws_security_group.executor.id
  description       = "REST API del FortiGate de laboratorio"
  cidr_ipv4         = var.fortigate_cidr
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "executor_s3" {
  security_group_id = aws_security_group.executor.id
  description       = "S3 por el punto de enlace de tipo gateway"
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "executor_endpoints" {
  security_group_id            = aws_security_group.executor.id
  description                  = "Secrets Manager y SNS por los puntos de enlace de interfaz"
  referenced_security_group_id = aws_security_group.endpoints.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

# Puntos de enlace de interfaz: solo aceptan a la Lambda ejecutora. Sin salida.
resource "aws_security_group" "endpoints" {
  name        = "${var.name_prefix}-endpoints"
  description = "Puntos de enlace de interfaz: entrada HTTPS solo desde la Lambda ejecutora"
  vpc_id      = aws_vpc.executor.id

  tags = { Name = "${var.name_prefix}-endpoints" }
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_executor" {
  security_group_id            = aws_security_group.endpoints.id
  description                  = "HTTPS desde la Lambda ejecutora"
  referenced_security_group_id = aws_security_group.executor.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

# Grupo de seguridad por defecto de la VPC: sin reglas, para que nada lo use
# por omisión.
resource "aws_default_security_group" "executor" {
  vpc_id = aws_vpc.executor.id

  tags = { Name = "${var.name_prefix}-default-sin-uso" }
}
