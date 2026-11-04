# Linea base de la primera entrega

Fecha: 3 de noviembre de 2026. Verificacion local en Windows x64, Python 3.11.9.
Comando inicial: `.\.venv-gui\Scripts\python.exe scripts/verify.py`.
Repetido en un entorno nuevo sin paquetes globales:
`.\.venv-harness\Scripts\python.exe scripts/verify.py --report-dir .harness/reports-clean`.

Resultado final: **12 controles aprobados; 282 pruebas aprobadas y 1 omitida**.

| Perfil | Resultado local |
| --- | --- |
| harness | 6 pruebas del runner; Ruff aprobado |
| pipeline | 208 passed, 1 skipped; Ruff aprobado |
| api | 26 passed; Ruff aprobado |
| desktop | 42 passed; Ruff aprobado |
| iac | 18 archivos HCL parseados; formato aprobado en las tres raices |

La prueba omitida es
`TestWallClockBudgetViaSignalBackstop::test_real_signal_backstop_terminates_pure_cpu_spin_with_no_toolkit_calls`
en `audit-pipeline/lambda/tests/test_sandbox.py`: requiere `signal.setitimer/SIGALRM`,
ausente en Windows. CI incluye el pipeline en Linux/Python 3.12 para ejecutarla.
La ejecucion de ese workflow todavia no esta demostrada localmente.

## Estado previo y correcciones

Antes de agregar el harness pasaban las mismas 276 pruebas de producto, con el
mismo skip. Ruff pasa al ejecutarlo desde el directorio propio del pipeline;
ejecutarlo desde la raiz con otro contexto produce errores de imports y un
falso error de longitud en el prompt. El runner fija el directorio de cada control.

Habia diferencias de formato en `terraform/iam.tf`,
`audit-pipeline/terraform/iam.tf`, `fortigate-sandbox-2026-06-07/main.tf` y
`fortigate-sandbox-2026-06-07/outputs.tf`. Se normalizaron con Terraform fmt:
alineacion, espacios y comillas de etiquetas, sin cambios en recursos o permisos.
Se evito `-diff` porque requiere el ejecutable externo `diff` en Windows.

El entorno existente tiene pytest 9.1.1, pytest-mock 3.16.0, Moto 5.2.3,
boto3 1.43.103 y Ruff 0.16.9; se agrego python-hcl2 7.3.1. Terraform local es
1.15.7. Tambien se creo `.venv-harness` sin paquetes globales, se instalaron los
manifests documentados y se repitieron los 12 controles: todos aprobados con las
282 pruebas y el mismo skip. Ese entorno utiliza pytest 8.3.5, pytest-mock 3.14.0
y Moto 5.1.4, las versiones declaradas para CI. `pip check` no encontro conflictos.
CI fija Terraform 1.9.8 y usa Linux/Python 3.12 para pipeline; esa combinacion
especifica todavia no esta verificada por la ejecucion local.

El entorno nuevo emitio una advertencia de Requests durante las suites pipeline y
API: Windows bloqueo la carga de la DLL de `charset_normalizer` 3.5.2 mediante una
politica de Control de aplicaciones. Se confirmo con una importacion directa.
Las suites pasan, pero ese resultado no prueba el funcionamiento completo de esa
dependencia en esta maquina. No se modifico la politica ni se oculto la advertencia.

## Evidencia y limites

El runner genera `.harness/reports/verification.json` y un log por control. Son
artefactos locales ignorados por Git; CI los publica con retencion de 14 dias.
La repeticion en el entorno nuevo esta en `.harness/reports-clean/`.
Los tests del runner verifican sustitucion de credenciales, propagacion de fallos,
timeouts, herramientas ausentes, continuacion tras fallos y seleccion de perfiles.

- El workflow fue revisado y su YAML parseado; no fue ejecutado en GitHub.
- El bootstrap se probo en un entorno virtual vacio usando las fuentes actuales;
  no se realizo un clon remoto separado.
- No se ejecutaron plan/apply/destroy, llamadas al modelo ni auditorias reales.
- IaC cubre parseo/formato; no incluye terraform validate ni Checkov como gates.
- No se consultaron credenciales, tfstate, SQLite local ni el estado de AWS.
- No hay suite para la copia Python `lambda/` de la raiz.
- No se probaron login institucional, accesibilidad ni instalacion de escritorio.
- Para bloquear merges faltaria configurar los required checks de la rama en GitHub.
