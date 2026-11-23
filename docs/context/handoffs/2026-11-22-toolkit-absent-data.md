# Un dato ausente termina en `indeterminate` (decisión 12)

- Fecha e identificador: 2026-11-22, toolkit-absent-data.
- Estado: implementado y documentado. **Verificado solo con tests y respuestas
  simuladas; no se volvió a ejecutar contra un FortiGate.**
- Rama: `fix/toolkit-absent-data`, creada desde `master` en `19acf70`, en un
  árbol de trabajo aislado. Sin cambios preexistentes.
- Commits propios: `4028d94` (rutas del catálogo), `edb55ed` (toolkit, sandbox,
  reporte y tests), `e8b547d` (API local y aplicación) y un commit documental
  posterior.
- Revisión del desarrollador y merge: pendientes. Push: no realizado. No se
  tocó ninguna otra rama.

## Objetivo y aceptación

Los scripts generados tratan un dato que no se pudo leer como un valor (lista
vacía, cero, `disable`) e informan `pass`. Se pidió que el harness, y no el
script, garantice que un hallazgo que depende de un dato ausente, ilegible o
imposiblemente vacío se informe como `indeterminate`, con un motivo que nombre
el endpoint, siguiendo la
[decisión 12](../decisions/12-datos-ausentes-indeterminate.md). Además:

- Sin debilitar el validador, los límites del sandbox, el cliente de solo
  lectura, las remediaciones como propuestas ni el cuidado de los secretos.
- Sin depender de que el script coopere; los scripts ya guardados en S3 deben
  obtener el comportamiento sin regenerarse.
- Regla explícita para un `fail` con datos ausentes.
- Reporte compatible con la API local y la aplicación.
- Corregir las rutas `system/dhcp/server` y `system/snmp/sysinfo`.

Evidencia del encargo (equipo de laboratorio, FortiOS 7.6.8, usuario de API
`super_admin_readonly`, diagnóstico con `--probe-global-scope`): está
transcripta en la decisión 12. No fue observada por este agente.

## Restricciones y autorizaciones

- Sin llamadas a AWS, sin contacto con un FortiGate, sin `terraform`.
- Sin leer `.env*`, `*.tfvars`, estado de Terraform, `audit-engine/local-runs/`,
  `.pps-api/` ni `pps-reporte*.json`.
- Commits locales con Conventional Commits y sin atribución; sin push ni merge.
- Se consultó la web solo para comprobar la convención de rutas `cmdb`, con
  búsquedas genéricas sin datos del proyecto.

## Decisiones

La regla, el contrato del hallazgo y la tabla de diferencias con el diseño
están en la sección «Implementación» de la decisión 12. Resumen de lo elegido
donde el diseño dejaba una opción abierta:

- **Atribución por endpoint declarado** (manifest más `endpoints_used`). Un
  control sin ninguna declaración hereda todas las lagunas de la corrida.
- **`fail` también se degrada**, conservando `reported_status`, como establece
  el punto 7 del diseño.
- **Solo `TrackedDict`**: las listas quedan como `list` comunes porque la
  respuesta se envuelve completa al leerla.
- **Claves aditivas solo cuando el toolkit interviene** (`reported_status`,
  `data_gaps`, `status_reason`); no se agregó `endpoints_read`.
- **La remediación se anula en el toolkit** para un hallazgo con lagunas.
- **El prompt del generador no se cambió**: obliga a regrabar las evaluaciones
  en vivo, que requieren AWS.
- **`NEVER_EMPTY_ENDPOINTS`** con los cuatro candidatos del diseño; falta la
  aprobación de los autores.

Rutas: `system.dhcp/server` y `system.snmp/sysinfo`. La primera figura en la
documentación pública de la biblioteca `fortigate-api`; la segunda se dedujo
de la misma convención. No se consultó la referencia de Fortinet ni un equipo.
`docs/base/06-conexion-fortigate.md` conserva las rutas anteriores porque
`docs/base/` es antecedente y no se reescribe.

## Skills

Ninguna skill del proyecto fue cargada; se siguieron `AGENTS.md` y el encargo.

## TDD y verificaciones

- Tests escritos primero en `test_toolkit.py`, `test_sandbox.py`,
  `test_reporter.py` y `test_fortigate_client.py`. Fallo inicial observado: 9
  fallos de comportamiento en los tres últimos (falso `pass` con
  administradores vacíos, endpoint ilegible, sección del reporte, rutas) y, en
  `test_toolkit.py`, un error de importación por los nombres nuevos, que no
  cuenta como fallo de comportamiento; sus casos se observaron en verde recién
  con la implementación.
- Un test existente cambió de contrato de forma deliberada:
  `test_handler_executor.py::TestPartialFortiGateEndpointFailureTolerance`.
  `fgt.get` ya no devuelve `None`, así que el control del endpoint ilegible es
  un hallazgo `indeterminate` y no una nota. La comprobación de que el control
  del endpoint legible conserva su `fail` no se modificó; el manifest del test
  ahora declara los endpoints de cada control.
- API local y aplicación: tests escritos primero; fallo inicial de 1 y 2 tests
  respectivamente.
- Resultado final (Windows, Python 3.12, `.venv` del clon principal):
  - Motor, `pytest -q -p no:cacheprovider`: 620 aprobados, 1 omitido (572 + 48).
  - `ruff check generator/ executor/ contracts/ legacy/ tests/ evals/ scripts/`:
    sin observaciones.
  - `ruff format --check` sobre las mismas rutas: 53 archivos conformes.
  - `evals/run_evals.py --mode offline`: código de salida 0.
  - `evals/run_evals.py --suite retrieval --mode offline`: código de salida 0.
  - API local: 38 aprobados (37 + 1). Aplicación, con
    `QT_QPA_PLATFORM=offscreen`: 51 aprobados (49 + 2). `ruff check` sin
    observaciones en ambas.
- No ejecutado: CI en Linux (sin push), Terraform y Checkov (no se tocó
  `infrastructure/`), evaluaciones en vivo, y ninguna corrida contra un equipo.
  El conteo de Linux en `ci.yml` (621 aprobados) es inferido, no observado.

## Pendientes y próximo paso

1. Repetir una corrida contra el equipo de laboratorio con esta rama y
   comprobar que los controles de administradores salen `indeterminate` y que
   `dhcp_servers` y `snmp_sysinfo` responden con las rutas nuevas.
2. Experimento pendiente: leer `system/admin` con un usuario de API de otro
   perfil, para saber por qué `super_admin_readonly` recibe la lista vacía. La
   visibilidad por perfil es una hipótesis, no una conclusión.
3. Medir cuántos `indeterminate` produce la regla con los scripts reales y
   decidir si la atribución por endpoint alcanza.
4. Decisiones de los autores: lista de endpoints que no pueden estar vacíos,
   conservar o no un `fail` afectado, cambio de prompt, copias con `dict(x)`.
5. Revisión del desarrollador y decisión de merge.
