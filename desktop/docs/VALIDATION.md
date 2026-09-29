# Validación de la entrega

Entorno: Windows x64, Python 3.11.9, PySide6 6.11.2.

## Ejecutado

Resultado de escritorio: **34 passed**. Ruff: **All checks passed**.

- Suite de escritorio: cálculos contra manifest, estados finales y parciales,
  denominadores vacíos, duplicados, controles desconocidos, referencias no verificables,
  pares de archivos incompatibles, formato/tamaño/hash preliminar de políticas.
- Cifrado, separación de caché por identidad, caducidad y rechazo de caché corrupta.
- URLs HTTPS, rechazo de redirects, paginación, rol remoto e idempotencia de la subida;
  el PUT temporal no recibe el token Bearer de la API.
- Arranque y navegación con Qt offscreen, filtros, roles, pérdida/recuperación de conexión,
  revocación, restauración de ejecución pendiente y descarte de respuestas después del logout.
- Layout de tres columnas y de una columna a 790 px, selección mediante teclado.
- Suite original: **164 passed, 1 skipped**. El skip corresponde a `signal.setitimer`
  en Windows, ya documentado por el proyecto.
- Ruff sobre `desktop/` y compilación de los módulos Python.
- Capturas deterministas de Resumen, Resultados y ventana estrecha, revisadas visualmente.
- Distribución Windows compilada con PyInstaller 6.22.3. Prueba del ejecutable
  `PPS-Desktop.exe --smoke-test`, en Qt offscreen, finalizada con código **0**.
  No se ejecutó el instalador ni se modificó la política de ejecución de PowerShell.

## No demostrado por estas pruebas

- Operación AWS real, aislamiento entre organizaciones en el servidor, URLs temporales
  reales, correlación de eventos S3 y transiciones persistidas del pipeline.
- Login con el proveedor institucional y sus políticas de audiencia/scopes.
- Accesibilidad con lector de pantalla real.
- Instalación/actualización en máquina Windows limpia, firma de código y SmartScreen.

Estos puntos requieren el servicio y las decisiones de despliegue de §11 de la spec.
No se modificó ni desplegó infraestructura AWS.
