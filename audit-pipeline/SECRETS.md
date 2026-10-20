# Credenciales del backend

Los handlers aceptan estos valores de `SecretString` en Secrets Manager:

- FortiGate: `{"token":"<token>"}`.
- Claude: `{"api_key":"<api key>"}`.

También se admite una credencial en texto simple por compatibilidad con
despliegues anteriores. Si el valor es JSON, debe ser un objeto con el campo
correspondiente de tipo string no vacío. JSON inválido, campos faltantes y
placeholders `REEMPLAZAR_CON_...` producen un error sin incluir el contenido
del secreto en el mensaje.

`FORTIGATE_HOST` sigue definiendo el destino. Un campo `host` dentro del secreto
no reemplaza esa variable de entorno.

La corrección está incluida tanto en `audit-pipeline/lambda/` como en `lambda/`.
Cada paquete incluye su propio `secret_values.py` porque se despliegan por
separado. Se debe publicar el paquete completo para actualizar las Lambdas.

Terraform actualmente crea versiones con placeholders. Cargar las credenciales
reales directamente en Secrets Manager mediante un canal autorizado; no sustituir
los placeholders por credenciales reales en los archivos `.tf`, ya que quedarían
en el código y el estado de Terraform. Este cambio no modifica valores remotos ni
el ciclo de vida de los recursos Terraform existentes.
