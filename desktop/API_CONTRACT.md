# Contrato del cliente de escritorio · v1

**Estado: adaptador cliente implementado; servicio AWS pendiente.** Las rutas propuestas
en la especificación no son endpoints existentes en este repositorio. Este documento fija
los campos adicionales necesarios para construir y verificar el adaptador remoto.

Todas las rutas reciben `Authorization: Bearer <access_token>` y TLS validado. El servidor
resuelve usuario, organización y dispositivos autorizados; no confía en roles ni IDs de
organización aportados por el cliente. Responde 403/404 sin revelar datos ajenos. GET de
exportación/documentos y PATCH de seguimiento también deben comprobar pertenencia.
Se rechazan redirects para no reenviar documentos o credenciales a otros destinos.

## Sesión y colecciones (extensiones a §6.1)

`GET /api/session` devuelve:

```json
{
  "organization": {"id": "org_1", "name": "Organización"},
  "user": {"id": "usr_1", "name": "Analista"},
  "role": "analyst",
  "environment": "LAB",
  "max_upload_bytes": 20971520,
  "devices": [{"id": "fgt_1", "name": "FortiGate", "connector_status": "connected", "last_checked_at": "2026-09-28T12:00:00Z"}],
  "capabilities": {"reaudit": false, "follow_up": false}
}
```

Roles: `admin`, `analyst`, `reader`. Esta respuesta es la autoridad de identidad de la GUI;
el servidor sigue siendo la autoridad en **cada operación**. `max_upload_bytes` debe ser
positivo y no superar el límite de la infraestructura. El lector solo consulta/exporta.

`GET /api/policies` y `GET /api/audits` devuelven
`{"items": [...], "next_cursor": "opaque-or-null"}`. El cursor se envía como `?cursor=...`.
Hasta 100 páginas por lectura; un cursor repetido produce error, no un bucle.
El MVP aplica los filtros de escritorio a la colección completa autorizada. La API puede
soportar además `q`, `status`, fechas y dispositivo para clientes futuros.

Cada entrada de políticas representa una versión:

```json
{
  "id": "pol_1", "version_id": "ver_1", "name": "Política institucional",
  "version_label": "2.1", "status": "procesando", "scope": "FortiGate laboratorio",
  "description": "Alcance del documento", "device_id": "fgt_1",
  "uploaded_by": "Analista", "uploaded_at": "2026-09-28T12:00:00Z",
  "mime_type": "application/pdf", "size": 2000, "sha256": "...",
  "check_count": 12, "review_status": "proposed", "last_audit_id": "aud_1"
}
```

`GET /api/policies/{id}` devuelve estos campos más `versions` y `checks` (del manifest).
Puede incluir `preview_text` y `original_download_available=true`. Si permite descargar,
`GET /api/policies/{id}/versions/{versionId}/document` entrega bytes privados autorizados.
No se devuelven claves S3 arbitrarias ni scripts generados.

Cada auditoría contiene:

```json
{
  "id": "aud_1", "run_id": null, "policy_version_id": "ver_1",
  "policy_name": "Política institucional", "policy_version": "2.1",
  "device": {"id": "fgt_1", "name": "FortiGate", "connector_status": "unknown", "last_checked_at": null},
  "status": "pending", "phase": "recibido", "started_at": "2026-09-28T12:00:00Z",
  "finished_at": null, "failure_reason": null,
  "events": [{"phase": "recibido", "timestamp": "2026-09-28T12:00:00Z", "message": "Objeto validado"}]
}
```

Las fases son eventos persistidos. El servicio no debe derivar eventos ficticios del tiempo
transcurrido. La colección devuelve el estado vigente, incluyendo eventos; el cliente
actual la sondea mientras existan ejecuciones activas. Si se implementa también
`GET /api/audits/{id}`, debe devolver el mismo objeto.

## Cargar e iniciar

1. `POST /api/policies`, `Idempotency-Key: uuid`. Body:
   `name`, `version_label`, `scope`, `description`, `device_id`, `sha256`, `size`,
   `mime_type`, `extension` (`pdf`/`docx`). El servidor asigna una clave opaca, crea la
   versión y la auditoría pendiente, y responde:

```json
{
  "policy_id": "pol_1", "version_id": "ver_1", "audit_id": "aud_1", "upload_id": "up_1",
  "upload": {"method": "PUT", "url": "https://...presigned...", "headers": {"Content-Type": "application/pdf"}}
}
```

2. PUT de bytes exactos a la URL temporal, sin token de la API. La autorización debe
   expirar, delimitar objeto y operación y exigir checksum cuando corresponda.
3. `POST /api/policies/{id}/versions/{versionId}/complete-upload`, misma clave de
   idempotencia, body `upload_id`, `sha256`, `size`. El servidor comprueba los bytes reales,
   confirma metadatos y reconcilia eventos S3 previos/posteriores. No alcanza con confiar
   en el tamaño/hash que envía el cliente. Responde 200/202 con JSON.

No hay reintentos automáticos de operaciones mutantes. Si falla la confirmación, la GUI
consulta el catálogo de auditorías y advierte revisar la ejecución antes de volver a subir.
La clave evita duplicar una misma transacción; no garantiza deduplicación entre dos cargas
manuales distintas. El servicio debe definir el tratamiento de cargas abandonadas y
confirmaciones perdidas. No se implementa reanudación de bytes de una subida interrumpida.

`POST /api/audits` se usa **solo** con `capabilities.reaudit=true`, body
`policy_version_id`, `device_id` y `Idempotency-Key`. Retorna 202; crea una ejecución nueva,
sin alterar reportes anteriores. Debe existir realmente el disparador desacoplado.

## Resultados

`GET /api/audits/{id}/results` devuelve:

```json
{
  "manifest": {"run_id": "run_1", "policy_sha256": "...", "checks": []},
  "report": {"run_id": "run_1", "status": "completed", "truncated": false,
             "timestamp": "2026-09-28T12:05:00Z", "findings": [], "notes": []},
  "next_cursor": null
}
```

Se mantiene el formato de `checks` y `findings` del pipeline. Cada página conserva el
mismo `run_id`. Manifest completo en la primera página, hallazgos paginados con cursor.
El servicio elimina cualquier script/credencial antes de responder. La GUI no necesita
`script_key`, `script_sha256` ni el código generado. Ante un fallo anterior a generar
manifest, el adaptador produce un manifest vacío con el `run_id` real del reporte de error.

Un finding puede extenderse con `id` opaco y `follow_up`:
`{"owner_id": "usr_2", "comment": "...", "status": "en revisión", "updated_at": "..."}`.
`PATCH /api/findings/{id}/follow-up` recibe los primeros tres campos y requiere capacidad
`follow_up=true`. El servidor registra actor/hora e historial. No cambia el resultado técnico.

`GET /api/audits/{id}/export?format=json|md` devuelve bytes autorizados del artefacto.
Límite de respuesta del cliente: 25 MB. Las exportaciones locales de caché/importación
incluyen una nota de procedencia; no se anuncian como autorización remota renovada.

`GET /api/dashboard` puede añadirse según la spec, pero la GUI actual calcula el tablero
a partir del par completo, de modo consistente con importación/caché. No consume agregados
que no permitan recuperar los controles y su denominador.

## Errores y validación antes de producción

Errores JSON con `code`, `message`, `correlation_id` y cabecera `X-Correlation-ID`.
La GUI usa mensajes locales por código HTTP y muestra la cabecera de correlación, evitando
revelar respuestas crudas que podrían contener credenciales, prompts o documentos.
401/403 durante refresco cierran sesión y borran la caché activa. Pérdida de red deja los
últimos datos visibles con aviso y deshabilita mutaciones.

El despliegue debe probar aislamiento entre organizaciones con cliente manipulado,
caducidad de URLs, validación de PDF/DOCX corruptos, reconciliación S3 fuera de orden,
reintentos/idempotencia, tokens expirados y fases después de reiniciar la aplicación.
Los mocks del cliente no demuestran esas propiedades del servidor.
