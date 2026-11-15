# Validación funcional local GUI/API

- Fecha: 2026-11-15. Identificador: local-functional-validation.
- Rama: `feature/local-functional-validation`, desde `master` en `96a99f7`.
- Objetivo autorizado: probar el flujo local con documentos y datos aislados,
  sin AWS ni FortiGate. No se modificó código de producción ni tests.
- Árbol inicial limpio. Cambios propios: este registro y el índice de handoffs.
- Skills: pps-local-api, pps-gui, pps-review y pps-handoff.
- Fuentes: manual API, contrato HTTP, implementación del cliente/ventana,
  servicios y tests existentes. No corresponde ciclo TDD de implementación.

## Smoke funcional ejecutado

Se ejecutó un script Python efímero por stdin con `.venv-gui`, PySide6 en
offscreen y una instancia real de `Window(demo_mode=False)`. La ventana usó
sus workers normales contra `create_server(Service(...), 0)` en loopback.
SQLite y preferencias se alojaron en `TemporaryDirectory` y se eliminaron al
terminar. No se usaron bases personales, credenciales ni servicios AWS.

Resultados aprobados:

1. Conexión real de la ventana a HTTP local y aviso de desarrollo local.
2. Carga con ApiClient de DOCX generado con python-docx y PDF con texto
   generado con pypdf; auditorías pendientes y descarga idéntica al original.
3. La GUI actualizó las dos políticas cargadas.
4. DOCX corrupto y PDF sin texto rechazados con 422; extensión no admitida
   rechazada; solo las dos cargas válidas quedaron habilitadas para envío.
5. Manifest con run_id o hash incorrectos rechazado mediante Service.finish.
6. Resultado sintético correlacionado incorporado al servicio y recuperado
   por HTTP; exportaciones JSON/Markdown incluyen el control C1 y el fallo.
7. La GUI recuperó el resultado mediante su actualización normal.
8. API detenida: GUI pasó a offline. API reiniciada en el mismo puerto con
   SQLite reabierta: GUI volvió a connected y el resultado se conservó.

El script terminó con código 0 y siete mensajes PASS. La carga se realizó
con el cliente HTTP del escritorio, no mediante diálogo de archivos ni
arrastre. Se comprobó recepción de resultados en la ventana, no inspección
visual humana de todos sus detalles. El reporte era una fixture explícita;
no acredita generación Bedrock ni consultas al firewall.

## Regresión y comprobaciones

`QT_QPA_PLATFORM=offscreen .venv-gui/Scripts/python.exe -m pytest -q
-p no:cacheprovider -c local-api/pyproject.toml local-api/tests gui/tests`:
86 aprobados en 11 segundos, sin fallos. Incluye tests de HTTPS local.
Registro documental revisado y `git diff --check` correcto. No se cambió
código ejecutable, por lo que no se repitió la suite del motor.

## Pendientes

- Prueba manual visible de selección/arrastre de archivos, lectura de detalles,
  navegación, accesibilidad y reinicio del proceso GUI.
- E2E real con Bedrock/FortiGate, sujeto a verificación de entorno y autorización.
- Merge de este registro pendiente de revisión y autorización; no hay push.
