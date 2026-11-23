# -----------------------------------------------------------------------------
# Host Ubuntu detrás del FortiGate (subred lan, sin dirección pública)
# -----------------------------------------------------------------------------

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "ubuntu" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.ubuntu_instance_type
  subnet_id                   = aws_subnet.lan.id
  private_ip                  = local.ubuntu_ip
  vpc_security_group_ids      = [aws_security_group.ubuntu.id]
  associate_public_ip_address = false

  # Sin par de claves ni acceso remoto: el host solo sirve una página de
  # prueba. La configuración inicial no necesita Internet.
  user_data = file("${path.module}/bootstrap/ubuntu-cloud-config.yaml")

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    encrypted   = true
  }

  tags        = { Name = "${var.name_prefix}-ubuntu" }
  volume_tags = { Name = "${var.name_prefix}-ubuntu" }

  lifecycle {
    # Canonical publica imágenes nuevas con frecuencia: no recrear el host por eso.
    ignore_changes = [ami]
  }
}
