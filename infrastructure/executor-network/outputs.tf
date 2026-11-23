# -----------------------------------------------------------------------------
# Valores para infrastructure/pipeline (misma forma que sus variables)
# -----------------------------------------------------------------------------

output "executor_subnet_ids" {
  description = "Lista de subredes para la variable executor_subnet_ids del pipeline."
  value       = [aws_subnet.private.id]
}

output "executor_security_group_ids" {
  description = "Lista de grupos de seguridad para la variable executor_security_group_ids del pipeline."
  value       = [aws_security_group.executor.id]
}

# -----------------------------------------------------------------------------
# Valores para infrastructure/fortigate-lab
# -----------------------------------------------------------------------------

output "peering_connection_id" {
  description = "Id del emparejamiento, para la variable peering_connection_id del laboratorio."
  value       = aws_vpc_peering_connection.lab.id
}

output "vpc_cidr" {
  description = "Bloque de esta VPC, para la variable peer_cidrs del laboratorio."
  value       = aws_vpc.executor.cidr_block
}

# -----------------------------------------------------------------------------
# Estado
# -----------------------------------------------------------------------------

output "vpc_id" {
  description = "Id de la VPC de la Lambda ejecutora."
  value       = aws_vpc.executor.id
}

output "peering_status" {
  description = "Estado del emparejamiento visto al último apply o refresh (pending-acceptance, active, etc.)."
  value       = aws_vpc_peering_connection.lab.accept_status
}

output "lab_route_created" {
  description = "Indica si existe la ruta hacia el laboratorio (peering_accepted = true)."
  value       = var.peering_accepted
}

output "interface_endpoints_enabled" {
  description = "Indica si están creados los puntos de enlace con costo por hora."
  value       = var.enable_interface_endpoints
}
