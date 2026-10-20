# API de políticas para desarrollo

API HTTP local compatible con `desktop/API_CONTRACT.md`. Permite desarrollar la GUI
sin OIDC: ofrece una identidad fija de desarrollo y un solo dispositivo (`fgt_local`).
Escucha exclusivamente en `127.0.0.1`; rechaza solicitudes con `Origin` y con otro
`Host`. No es un servicio multiusuario ni un despliegue público de AWS.

## Iniciar

Desde la raíz del repositorio, con Python 3.11 o superior:

```powershell
.\.venv-gui\Scripts\python -m pip install -e './audit-pipeline/api[dev]'
.\.venv-gui\Scripts\python audit-pipeline/api/launch.py serve
```

En otra terminal:

```powershell
.\.venv-gui\Scripts\python desktop/launch.py
```

En **Configuración → API local de desarrollo**, usar `http://127.0.0.1:8765` y
**Conectar API local**. La interfaz habilita la carga y el reanálisis sin abrir el
navegador. HTTP está permitido únicamente con esta conexión explícita, a esa IP y
al mismo puerto; la conexión institucional sigue exigiendo HTTPS y OIDC.

Los datos se guardan en `.pps-api/development.sqlite3`, ignorado por Git. Incluye
documentos originales, metadatos, comprobantes de idempotencia, eventos y resultados.
El contenido no está cifrado por la API: usar documentos de prueba y proteger la
cuenta del sistema. Cerrar y volver a abrir el servidor conserva las cargas.
Para elegir otra base o puerto:

```powershell
.\.venv-gui\Scripts\python audit-pipeline/api/launch.py --database .pps-api/otro.sqlite3 serve --port 8766
```

La opción `--database` debe preceder al subcomando. Usar la misma ruta absoluta o
ejecutar todos los comandos desde la raíz para compartir la base.

## Flujo implementado

1. `POST /api/policies`: valida metadatos, crea política, versión y auditoría pendiente.
   Requiere `Idempotency-Key`; repetir la misma solicitud devuelve los mismos IDs.
   Reutilizar la clave con otro contenido devuelve 409.
2. `PUT /uploads/{upload_id}?token=...`: autorización local temporal de 15 minutos.
   Comprueba MIME, tamaño máximo de 20 MiB y SHA-256 de los bytes recibidos.
3. `POST /api/policies/{id}/versions/{version_id}/complete-upload`: vuelve a comprobar
   los bytes persistidos, interpreta PDF/DOCX y rechaza documentos corruptos,
   cifrados o sin texto. Limita expansión ZIP y cantidad de páginas/entradas. Confirma
   una sola vez y deja la auditoría en cola. Una carga confirmada es inmutable.
4. `GET /api/policies` y `GET /api/audits`: colecciones paginadas de 50 elementos;
   detalle por ID, vista previa textual de hasta 100.000 caracteres y descarga original.
5. `GET /api/audits/{id}/results`: manifest y reporte saneados cuando están disponibles;
   antes responde 409. Exportación `json` o `md`. El Markdown se construye desde el
   reporte saneado, no es una copia del artefacto Markdown de S3.
6. `POST /api/audits`: encola una nueva ejecución de una versión confirmada con una
   clave de idempotencia nueva, conservando los resultados de las anteriores.

Cada carga crea una política con una versión; aún no hay una operación para añadir
versiones a una política existente. El dashboard sigue calculándose en la GUI.
El seguimiento de hallazgos está deshabilitado (`follow_up=false`).

## Procesamiento real con el pipeline AWS existente

La carga HTTP **no llama a AWS**. Queda pendiente hasta ejecutar el comando de envío.
El puente usa credenciales de la cadena habitual de boto3 (por ejemplo un perfil
temporal), nunca credenciales enviadas desde la GUI.

Se requieren los recursos de `audit-pipeline/terraform/` desplegados, secretos válidos
y conectividad de la Lambda ejecutora con FortiGate. `fgt_local` representa el único
FortiGate configurado mediante `FORTIGATE_HOST` en ese despliegue. No se permite
seleccionar destinos arbitrarios desde la API; el estado del conector permanece
`unknown` porque no se ha implementado un sondeo de salud.

```powershell
# Envía todos los trabajos confirmados pendientes al bucket del pipeline.
.\.venv-gui\Scripts\python audit-pipeline/api/launch.py aws dispatch --policies-bucket NOMBRE_POLICIES --reports-bucket NOMBRE_REPORTS

# Ejecutar después, y repetir mientras se espera la terminación del pipeline.
.\.venv-gui\Scripts\python audit-pipeline/api/launch.py aws sync --policies-bucket NOMBRE_POLICIES --reports-bucket NOMBRE_REPORTS
```

El perfil necesita `s3:PutObject` en `policies/*` del bucket de políticas,
`s3:ListBucket` para el prefijo `reports/` y `s3:GetObject` en `reports/*` y
`artifacts/*/manifest.json` del bucket de reportes. No necesita obtener secretos,
descargar scripts ni invocar Lambda directamente. La notificación de S3 existente
dispara el generador al escribir `policies/{audit_id}.pdf|docx`, **después** de la
validación. El `policy_key` de los reportes permite correlacionar el `run_id` real
con el `audit_id` persistido. Para fallos anteriores al manifest se proporciona uno
vacío usando el `run_id` real del reporte y el hash de la carga confirmada.

Solo se registran hechos confirmados: documento validado, S3 recibió el documento
y reporte recuperado. No se inventan las fases internas de las Lambdas. No hay
worker automático: el sondeo de la GUI consulta SQLite; `aws sync` incorpora los
resultados de AWS a esa base.

La cola marca el envío antes de contactar S3. Un envío ambiguo o interrumpido no se
repite automáticamente y boto3 se configura sin reintentos en este comando. Ejecutar
`aws sync` primero para verificar si ya existe el reporte; si no, comprobar el objeto
y los logs del pipeline antes de solicitar una nueva auditoría. Un fallo sin reporte
no se convierte en éxito ni en resultado vacío. Las cargas abandonadas y estos
trabajos se conservan para inspección; todavía no hay expiración/limpieza automática
de registros ni recuperación automática de trabajos atascados.

S3 puede entregar eventos duplicados y el pipeline todavía crea un UUID por
invocación. Si `sync` encuentra múltiples runs para la misma auditoría, registra el
conflicto y no elige un resultado arbitrariamente. Puede resolverse adjuntando
explícitamente los artefactos elegidos con el comando siguiente. Un resultado ya
asociado es inmutable; duplicados que aparezcan después no lo sobrescriben.

`sync` enumera reportes para reconciliar: está pensado para un sandbox pequeño.
Un despliegue de producción debe sustituirlo por eventos e índices persistidos,
instrumentar las fases en las Lambdas y deduplicar sus invocaciones.

## Adjuntar reportes existentes

Para desarrollar resultados sin ejecutar AWS, se pueden asociar artefactos reales
de una auditoría sobre el mismo documento:

```powershell
.\.venv-gui\Scripts\python audit-pipeline/api/launch.py import-result aud_ID ruta/manifest.json ruta/report.json
```

Se exige coincidencia del `run_id`, del `policy_key` entre artefactos y del SHA-256
del documento. Si la auditoría ya fue enviada a AWS, el `policy_key` también debe
coincidir con el objeto registrado. Se retiran campos de script y credenciales
identificables antes de guardar los resultados para la GUI. El comando no ejecuta
scripts. No puede reemplazar resultados ya asociados por otros diferentes.

## Pruebas

```powershell
.\.venv-gui\Scripts\python -m pytest -q -c audit-pipeline/api/pyproject.toml audit-pipeline/api/tests
.\.venv-gui\Scripts\python -m pytest -q desktop/tests
```

Pruebas HTTP reales en loopback con el cliente de escritorio, persistencia SQLite,
idempotencia concurrente, integridad/expiración de cargas, validación de documentos,
resultados inmutables, paginación y puente S3 con Moto. No prueban un despliegue AWS.

Pendientes para un servicio remoto: identidad/OIDC, autorización por organización,
hosting HTTPS, persistencia compartida, carga directa a S3, aislamiento del parser,
retención, instrumentación de fases y recuperación de trabajos. El servidor local
no debe exponerse mediante proxies o túneles como sustituto de esos componentes.
