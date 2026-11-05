---
name: pps-gui
description: "Desarrollar o corregir la GUI PySide6 de PPS, sus vistas y su cliente HTTP/HTTPS. Usar para cambios en gui/; no para implementar endpoints del servidor ni operar AWS."
---

# GUI PPS

Leer [el contrato](../../../AGENTS.md), [el manual GUI](../../../gui/README.md)
y [el contrato API](../../../gui/API_CONTRACT.md) según el cambio.

- Localizar el comportamiento en `gui/pps_desktop/`. Mantener reglas de
  presentación en la GUI y autorización de organización/dispositivo en el servidor.
- Para lógica de resultados, escribir primero casos de dominio; para transporte,
  casos en el cliente API; para interacción, pruebas de widgets con Qt offscreen.
  Observar el fallo antes de implementar, conforme al contrato TDD.
- Mantener las llamadas de red fuera del hilo de UI mediante el mecanismo de
  tareas existente. Comprobar estados de carga, error y reconexión afectados.
- Distinguir conexión institucional HTTPS/OIDC de desarrollo loopback explícito.
  La CA local no debe desactivar validación de certificado/nombre. Preservar el
  control de origen, esquema y redirects al subir documentos.
- No introducir boto3, credenciales AWS ni conexiones FortiGate en la GUI.
  Usar datos de prueba sin secretos para capturas o pruebas.

Verificar desde `gui/` con el Python del entorno seleccionado: pytest con
`QT_QPA_PLATFORM=offscreen`, Ruff y formato en archivos afectados. Si cambia
el contrato de transporte, ejecutar también los tests de integración de
`local-api/`. Reportar el resultado y las limitaciones visuales no comprobadas.
