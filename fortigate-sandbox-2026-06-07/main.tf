# 1. Red aislada para la prueba (VPC)
resource "aws_vpc" "sandbox_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  tags = { Name = "UNNE-Sandbox-VPC" }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.sandbox_vpc.id
}

resource "aws_subnet" "public_subnet" {
  vpc_id                  = aws_vpc.sandbox_vpc.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
}

resource "aws_route_table" "rt" {
  vpc_id = aws_vpc.sandbox_vpc.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
}

resource "aws_route_table_association" "a" {
  subnet_id      = aws_subnet.public_subnet.id
  route_table_id = aws_route_table.rt.id
}

# 2. Grupo de Seguridad (Firewall de AWS)
resource "aws_security_group" "allow_fgt" {
  name   = "allow_fortigate_mgmt"
  vpc_id = aws_vpc.sandbox_vpc.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] 
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 3. Búsqueda automática de la AMI de Fortinet (On-Demand)
data "aws_ami" "fortigate_latest" {
  most_recent = true
  owners      = ["aws-marketplace"]

  filter {
    name   = "name"
    # Busca la versión VM64 On-Demand en la región configurada
    values = ["FortiGate-VM64-AWSONDEMAND*"]
  }
}

# 4. Instancia de FortiGate
resource "aws_instance" "fortigate" {
  # Usa la AMI encontrada automáticamente
  ami                    = data.aws_ami.fortigate_latest.id 
  instance_type          = "c5.large"
  subnet_id              = aws_subnet.public_subnet.id
  vpc_security_group_ids = [aws_security_group.allow_fgt.id]
  iam_instance_profile   = aws_iam_instance_profile.fortigate_profile.name

  tags = {
    Name        = "FortiGate-Sandbox"
    Project     = "PPS-Framework-Seguridad"
    Environment = "Isolated-Test"
  }
}