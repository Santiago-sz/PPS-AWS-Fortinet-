# =============================================================================
# OUTPUTS — Knowledge Base administrada
# =============================================================================

output "knowledge_base_id" {
  description = "Id de la Knowledge Base. Es el valor de la variable knowledge_base_id del módulo infrastructure/pipeline"
  value       = aws_bedrockagent_knowledge_base.this.id
}

output "knowledge_base_arn" {
  description = "ARN de la Knowledge Base"
  value       = aws_bedrockagent_knowledge_base.this.arn
}

output "data_source_id" {
  description = "Id del data source S3, necesario para iniciar un trabajo de ingesta"
  value       = aws_bedrockagent_data_source.documents.data_source_id
}

output "knowledge_bucket" {
  description = "Nombre del bucket S3 donde se suben los documentos de la Knowledge Base"
  value       = aws_s3_bucket.knowledge.bucket
}
