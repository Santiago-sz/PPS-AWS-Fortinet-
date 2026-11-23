# -----------------------------------------------------------------------------
# FortiGate-VM bajo demanda (PAYG) del Marketplace
# -----------------------------------------------------------------------------

# La imagen se identifica por el código de producto del Marketplace y por la
# versión en el nombre ("FortiGate-VM64-AWSONDEMAND build3744 (7.6.8) GA-...").
# Requiere haber aceptado la suscripción al producto en la cuenta.
data "aws_ami" "fortigate" {
  most_recent = true
  owners      = ["aws-marketplace"]

  filter {
    name   = "product-code"
    values = [var.fortigate_product_code]
  }

  filter {
    name   = "name"
    values = ["FortiGate-VM64-AWSONDEMAND build* (${var.fortios_version}) GA*"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

locals {
  # Volúmenes adicionales que trae la imagen (el disco de registros). Se
  # declaran para poder cifrarlos y pasarlos a gp3 sin suponer su nombre.
  fortigate_extra_volumes = {
    for m in data.aws_ami.fortigate.block_device_mappings :
    m.device_name => m.ebs
    if m.device_name != data.aws_ami.fortigate.root_device_name && try(m.ebs.snapshot_id, "") != ""
  }

  # Un bloque CIDR en la forma "dirección máscara" que usa la CLI de FortiOS.
  admin_sources = [
    for i, c in var.admin_cidrs : {
      name = "adm-origen-${i + 1}"
      ip   = cidrhost(c, 0)
      mask = cidrnetmask(c)
    }
  ]
  peer_sources = [
    for i, c in var.peer_cidrs : {
      name = "vpc-par-${i + 1}"
      ip   = cidrhost(c, 0)
      mask = cidrnetmask(c)
    }
  ]

  # Administradores adicionales y usuarios locales de ejemplo. Las contraseñas
  # se generan y quedan solo en el estado local, que Git ignora.
  extra_admins = ["netops", "auditoria", "soporte-ext"]
  local_users  = ["jperez", "mgomez"]
}

resource "random_password" "admin" {
  for_each = toset(local.extra_admins)

  length = 24
  # Sin símbolos: la contraseña viaja dentro de un comando de la CLI de FortiOS.
  special     = false
  min_lower   = 2
  min_upper   = 2
  min_numeric = 2
}

resource "random_password" "local_user" {
  for_each = toset(local.local_users)

  length      = 24
  special     = false
  min_lower   = 2
  min_upper   = 2
  min_numeric = 2
}

# port1 = wan. La dirección pública es una Elastic IP para que no cambie al
# detener e iniciar la instancia.
resource "aws_network_interface" "fortigate_wan" {
  description     = "${var.name_prefix} FortiGate port1 (wan)"
  subnet_id       = aws_subnet.wan.id
  private_ips     = [local.fortigate_ips.wan]
  security_groups = [aws_security_group.fortigate_wan.id]

  tags = { Name = "${var.name_prefix}-fgt-port1-wan" }
}

# port2 = lan y port3 = dmz. Sin comprobación de origen y destino: el FortiGate
# reenvía tráfico que no va dirigido a sus propias direcciones.
resource "aws_network_interface" "fortigate_lan" {
  description       = "${var.name_prefix} FortiGate port2 (lan)"
  subnet_id         = aws_subnet.lan.id
  private_ips       = [local.fortigate_ips.lan]
  security_groups   = [aws_security_group.fortigate_internal.id]
  source_dest_check = false

  tags = { Name = "${var.name_prefix}-fgt-port2-lan" }
}

resource "aws_network_interface" "fortigate_dmz" {
  description       = "${var.name_prefix} FortiGate port3 (dmz)"
  subnet_id         = aws_subnet.dmz.id
  private_ips       = [local.fortigate_ips.dmz]
  security_groups   = [aws_security_group.fortigate_internal.id]
  source_dest_check = false

  tags = { Name = "${var.name_prefix}-fgt-port3-dmz" }
}

resource "aws_eip" "fortigate" {
  domain            = "vpc"
  network_interface = aws_network_interface.fortigate_wan.id

  tags = { Name = "${var.name_prefix}-fgt-eip" }

  depends_on = [aws_internet_gateway.lab]
}

# Configuración inicial en el formato MIME que usa la plantilla oficial de
# Fortinet para AWS (fortinet/fortigate-terraform-deploy, aws/7.6/single):
# una parte text/x-shellscript con comandos de la CLI de FortiOS. FortiOS la
# aplica una sola vez, en el primer arranque.
data "cloudinit_config" "fortigate" {
  gzip          = false
  base64_encode = false

  part {
    filename     = "config"
    content_type = "text/x-shellscript"
    content = templatefile("${path.module}/bootstrap/fortigate.conf.tftpl", {
      hostname        = var.fortigate_hostname
      api_user        = var.api_user_name
      vpc_ip          = cidrhost(var.vpc_cidr, 0)
      vpc_mask        = cidrnetmask(var.vpc_cidr)
      vpc_dns         = cidrhost(var.vpc_cidr, 2)
      wan_ip          = local.fortigate_ips.wan
      lan_ip          = local.fortigate_ips.lan
      dmz_ip          = local.fortigate_ips.dmz
      lan_net         = cidrhost(local.subnet_cidrs.lan, 0)
      dmz_net         = cidrhost(local.subnet_cidrs.dmz, 0)
      subnet_mask     = cidrnetmask(local.subnet_cidrs.lan)
      lan_gateway     = cidrhost(local.subnet_cidrs.lan, 1)
      lan_users_start = cidrhost(local.subnet_cidrs.lan, 100)
      lan_users_end   = cidrhost(local.subnet_cidrs.lan, 199)
      ti_start        = cidrhost(local.subnet_cidrs.lan, 50)
      ti_end          = cidrhost(local.subnet_cidrs.lan, 59)
      ubuntu_ip       = local.ubuntu_ip
      srv_db_ip       = cidrhost(local.subnet_cidrs.lan, 30)
      srv_monitor_ip  = cidrhost(local.subnet_cidrs.lan, 40)
      srv_web_ip      = cidrhost(local.subnet_cidrs.dmz, 20)
      srv_app_ip      = cidrhost(local.subnet_cidrs.dmz, 21)
      srv_dir_ip      = cidrhost(local.subnet_cidrs.dmz, 25)
      srv_syslog_ip   = cidrhost(local.subnet_cidrs.dmz, 30)
      branch_net      = cidrhost(cidrsubnet(var.vpc_cidr, 8, 200), 0)
      admin_sources   = local.admin_sources
      peer_sources    = local.peer_sources
      admin_passwords = { for k, v in random_password.admin : k => v.result }
      user_passwords  = { for k, v in random_password.local_user : k => v.result }
    })
  }
}

resource "aws_instance" "fortigate" {
  ami               = data.aws_ami.fortigate.id
  instance_type     = var.fortigate_instance_type
  availability_zone = local.az
  user_data         = data.cloudinit_config.fortigate.rendered

  # Sin par de claves: el primer ingreso usa el usuario admin y, como
  # contraseña, el id de la instancia (ver README.md).

  # Las tres interfaces se conectan en el lanzamiento, no después, para que
  # port2 y port3 existan cuando FortiOS aplica la configuración inicial.
  network_interface {
    device_index         = 0
    network_interface_id = aws_network_interface.fortigate_wan.id
  }

  network_interface {
    device_index         = 1
    network_interface_id = aws_network_interface.fortigate_lan.id
  }

  network_interface {
    device_index         = 2
    network_interface_id = aws_network_interface.fortigate_dmz.id
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2; FortiOS lo usa desde 6.4.3
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    encrypted   = true
  }

  dynamic "ebs_block_device" {
    for_each = local.fortigate_extra_volumes

    content {
      device_name = ebs_block_device.key
      volume_size = tonumber(ebs_block_device.value.volume_size)
      volume_type = "gp3"
      encrypted   = true
    }
  }

  tags        = { Name = "${var.name_prefix}-fortigate" }
  volume_tags = { Name = "${var.name_prefix}-fortigate" }

  lifecycle {
    # FortiOS lee la configuración inicial solo en el primer arranque, y la
    # imagen "más reciente" puede cambiar si Fortinet la vuelve a publicar.
    # Para aplicar un cambio en cualquiera de las dos hay que recrear la
    # instancia de forma explícita: terraform apply -replace=aws_instance.fortigate
    ignore_changes = [ami, user_data]

    precondition {
      condition     = length(data.cloudinit_config.fortigate.rendered) <= 16384
      error_message = "La configuración inicial del FortiGate supera los 16 KB que admite el user-data de EC2."
    }
  }

  depends_on = [aws_route.wan_default]
}
