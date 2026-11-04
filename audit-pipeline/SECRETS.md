# Credenciales del backend

El único secreto del pipeline es el token de FortiGate. El modelo (Claude)
se invoca a través de Amazon Bedrock con la identidad IAM del rol de cada
Lambda (`bedrock:InvokeModel` sobre `foundation-model/anthropic.*` y el
`inference-profile/*` de la cuenta, ver `terraform/iam.tf`): no existe
ninguna API key de Anthropic que cargar, rotar ni proteger. El modelo se
selecciona con la variable de entorno `BEDROCK_MODEL_ID` (Terraform:
`var.bedrock_model_id`, por defecto `us.anthropic.claude-sonnet-4-6`).

## Token de FortiGate

Los handlers aceptan este valor de `SecretString` en Secrets Manager:

- FortiGate: `{"token":"<token>"}`.

También se admite una credencial en texto simple por compatibilidad con
despliegues anteriores. Si el valor es JSON, debe ser un objeto con el campo
`token` de tipo string no vacío. JSON inválido, campos faltantes y
placeholders `REEMPLAZAR_CON_...` producen un error sin incluir el contenido
del secreto en el mensaje.

`FORTIGATE_HOST` sigue definiendo el destino. Un campo `host` dentro del secreto
no reemplaza esa variable de entorno.

Terraform crea la versión inicial del secreto con un placeholder y la marca
con `lifecycle { ignore_changes = [secret_string] }`: cargar el token real
directamente en Secrets Manager mediante un canal autorizado (ver el output
`next_steps` del apply) y un `terraform apply` posterior nunca lo pisará. No
sustituir el placeholder por credenciales reales en los archivos `.tf`, ya que
quedarían en el código y el estado de Terraform.

## Acceso al modelo en Bedrock

Antes del primer run hay que habilitar el acceso al modelo una única vez por
cuenta y región (consola de Bedrock, "Model access") y verificar que el perfil
de inferencia configurado exista en la región de despliegue:

```bash
aws bedrock list-inference-profiles --region <aws_region> \
  --query "inferenceProfileSummaries[?inferenceProfileId=='us.anthropic.claude-sonnet-4-6']"
```

Sin ese paso la Lambda falla con `AccessDeniedException` aunque la política
IAM sea correcta; el error queda registrado en el evento `llm_call` y el run
termina con `status=could_not_audit` y `failure_reason=ClaudeCallError:...`.

## Alcance

Cada paquete (`audit-pipeline/lambda/` y el `lambda/` legacy de la raíz)
incluye su propio `secret_values.py` porque se despliegan por separado. Se
debe publicar el paquete completo para actualizar las Lambdas.
