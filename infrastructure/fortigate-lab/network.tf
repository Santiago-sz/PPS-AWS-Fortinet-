# -----------------------------------------------------------------------------
# Red: una VPC, una zona de disponibilidad y tres subredes (wan, lan, dmz)
# -----------------------------------------------------------------------------

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  az = coalesce(var.availability_zone, data.aws_availability_zones.available.names[0])

  subnet_cidrs = {
    wan = cidrsubnet(var.vpc_cidr, 8, 0)
    lan = cidrsubnet(var.vpc_cidr, 8, 1)
    dmz = cidrsubnet(var.vpc_cidr, 8, 2)
  }

  # Direcciones fijas: la configuración inicial del FortiGate las referencia.
  fortigate_ips = {
    wan = cidrhost(local.subnet_cidrs.wan, 10)
    lan = cidrhost(local.subnet_cidrs.lan, 10)
    dmz = cidrhost(local.subnet_cidrs.dmz, 10)
  }
  ubuntu_ip = cidrhost(local.subnet_cidrs.lan, 20)
}

resource "aws_vpc" "lab" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id

  tags = { Name = "${var.name_prefix}-igw" }
}

resource "aws_subnet" "wan" {
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = local.subnet_cidrs.wan
  availability_zone       = local.az
  map_public_ip_on_launch = false

  tags = { Name = "${var.name_prefix}-wan" }
}

resource "aws_subnet" "lan" {
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = local.subnet_cidrs.lan
  availability_zone       = local.az
  map_public_ip_on_launch = false

  tags = { Name = "${var.name_prefix}-lan" }
}

resource "aws_subnet" "dmz" {
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = local.subnet_cidrs.dmz
  availability_zone       = local.az
  map_public_ip_on_launch = false

  tags = { Name = "${var.name_prefix}-dmz" }
}

# wan: salida directa a Internet. Es la única subred con ruta al gateway.
resource "aws_route_table" "wan" {
  vpc_id = aws_vpc.lab.id

  tags = { Name = "${var.name_prefix}-rt-wan" }
}

resource "aws_route" "wan_default" {
  route_table_id         = aws_route_table.wan.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.lab.id
}

resource "aws_route_table_association" "wan" {
  subnet_id      = aws_subnet.wan.id
  route_table_id = aws_route_table.wan.id
}

# lan y dmz: todo el tráfico saliente pasa por la interfaz del FortiGate en
# esa subred. No tienen ruta propia a Internet.
resource "aws_route_table" "lan" {
  vpc_id = aws_vpc.lab.id

  tags = { Name = "${var.name_prefix}-rt-lan" }
}

resource "aws_route" "lan_default" {
  route_table_id         = aws_route_table.lan.id
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = aws_network_interface.fortigate_lan.id
}

resource "aws_route_table_association" "lan" {
  subnet_id      = aws_subnet.lan.id
  route_table_id = aws_route_table.lan.id
}

resource "aws_route_table" "dmz" {
  vpc_id = aws_vpc.lab.id

  tags = { Name = "${var.name_prefix}-rt-dmz" }
}

resource "aws_route" "dmz_default" {
  route_table_id         = aws_route_table.dmz.id
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = aws_network_interface.fortigate_dmz.id
}

resource "aws_route_table_association" "dmz" {
  subnet_id      = aws_subnet.dmz.id
  route_table_id = aws_route_table.dmz.id
}
