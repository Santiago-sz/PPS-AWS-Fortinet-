# -----------------------------------------------------------------------------
# Acceso
# -----------------------------------------------------------------------------

output "fortigate_public_ip" {
  description = "Dirección pública (Elastic IP) de la interfaz WAN del FortiGate."
  value       = aws_eip.fortigate.public_ip
}

output "fortigate_admin_url" {
  description = "URL de la interfaz web y de la REST API. Solo responde a los orígenes de admin_cidrs."
  value       = "https://${aws_eip.fortigate.public_ip}"
}

output "demo_web_url" {
  description = "Reenvío de demostración: puerto 8080 del FortiGate hacia el puerto 80 del host Ubuntu."
  value       = "http://${aws_eip.fortigate.public_ip}:8080"
}

output "fortigate_instance_id" {
  description = "Id de la instancia del FortiGate. Es la contraseña inicial del usuario admin."
  value       = aws_instance.fortigate.id
}

output "ubuntu_instance_id" {
  description = "Id de la instancia del host Ubuntu."
  value       = aws_instance.ubuntu.id
}

output "fortigate_ami" {
  description = "Imagen del Marketplace resuelta para la versión pedida."
  value = {
    id   = data.aws_ami.fortigate.id
    name = data.aws_ami.fortigate.name
  }
}

output "api_user_name" {
  description = "Usuario de REST API de solo lectura. El token se genera en el equipo, no acá."
  value       = var.api_user_name
}

output "admin_passwords" {
  description = "Contraseñas de los administradores adicionales creados por la configuración inicial."
  value       = { for k, v in random_password.admin : k => v.result }
  sensitive   = true
}

output "local_user_passwords" {
  description = "Contraseñas de los usuarios locales de ejemplo."
  value       = { for k, v in random_password.local_user : k => v.result }
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Red (los necesita la fase de conexión privada por emparejamiento de VPC)
# -----------------------------------------------------------------------------

output "vpc_id" {
  description = "Id de la VPC del laboratorio."
  value       = aws_vpc.lab.id
}

output "vpc_cidr" {
  description = "Bloque de la VPC del laboratorio."
  value       = aws_vpc.lab.cidr_block
}

output "subnet_ids" {
  description = "Ids de las subredes."
  value = {
    wan = aws_subnet.wan.id
    lan = aws_subnet.lan.id
    dmz = aws_subnet.dmz.id
  }
}

output "subnet_cidrs" {
  description = "Bloques de las subredes."
  value       = local.subnet_cidrs
}

output "route_table_ids" {
  description = "Ids de las tablas de rutas."
  value = {
    wan = aws_route_table.wan.id
    lan = aws_route_table.lan.id
    dmz = aws_route_table.dmz.id
  }
}

output "fortigate_private_ips" {
  description = "Direcciones privadas del FortiGate en cada subred (port1, port2, port3)."
  value       = local.fortigate_ips
}

output "ubuntu_private_ip" {
  description = "Dirección privada del host Ubuntu."
  value       = local.ubuntu_ip
}

output "availability_zone" {
  description = "Zona de disponibilidad usada."
  value       = local.az
}
