---
name: pps-local-api
description: "Desarrollar o corregir el servidor local PPS, sus servicios, SQLite o el puente AWS explícito en local-api/. No usar para desplegar Terraform ni cambiar el motor de auditoría."
---

# API local PPS

Consultar [el manual](../../../local-api/README.md),
[el contrato HTTP](../../../gui/API_CONTRACT.md) y
[la arquitectura](../../../docs/context/repository-layout.md).

Elegir el área según el comportamiento:

| Área | Responsabilidad y pruebas iniciales |
|---|---|
| `pps_api/server/` | Rutas, límites y HTTP/HTTPS; probar códigos, cabeceras, origen y TLS |
| `pps_api/services/` | Cargas, idempotencia y resultados; probar aceptación y rechazo del caso de uso |
| `pps_api/domain/` y `storage/` | Precondiciones y persistencia; probar reapertura, transacciones e inmutabilidad |
| `pps_api/aws/` | Dispatch, sync, aprobación y configuración; probar con mocks/Moto sin AWS real |

Escribir los casos antes de implementar. El servidor debe importar sin SDK AWS
ni módulos GUI. Las pruebas de integración pueden usar el cliente GUI; eso no
autoriza dependencia de producción en ese paquete.

Preservar uploads acotados, comprobación de hash/MIME, protección Host/Origin,
idempotencia e inmutabilidad. Una carga local no despacha a AWS automáticamente.
Conservar adaptadores públicos de compatibilidad cuando un movimiento cambie imports.

Para AWS, mantener la reserva previa al envío y evitar reintentos de operaciones
ambiguas que puedan duplicar auditorías. No fabricar progreso ni elegir un run
arbitrario ante conflictos. Los tests nunca requieren secretos reales.

Ejecutar pytest desde `local-api/`, Ruff y formato en lo afectado; si cambia el
transporte, comprobar también el cliente GUI. Un cambio de SQLite debe especificar
compatibilidad de datos existentes y cómo se verificó sin usar bases personales.
