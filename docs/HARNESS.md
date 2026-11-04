# Harness de desarrollo: primera entrega

## Preparar un clon limpio

Python 3.12 para pipeline/CI; escritorio admite Python 3.11 en Windows. Desde la raiz:

```powershell
python -m venv .venv-harness
.\.venv-harness\Scripts\python -m pip install -r scripts/requirements-harness.txt -r scripts/requirements-tests.txt
.\.venv-harness\Scripts\python -m pip install -r audit-pipeline/lambda/requirements.txt -e ./audit-pipeline/api -e ./desktop
.\.venv-harness\Scripts\python scripts/verify.py harness pipeline api desktop
```

En Linux usar `.venv-harness/bin/python`. Para pruebas Qt en Linux pueden requerirse
bibliotecas del sistema; CI prueba la GUI en Windows. La instalacion de paquetes
requiere acceso al indice de Python. Los manifests fijan herramientas y dependencias
directas; aun no existe un lock completo de dependencias transitivas.

Para IaC instalar Terraform 1.9.8 (version usada por CI) y agregarlo al PATH:

```powershell
.\.venv-harness\Scripts\python scripts/verify.py iac
```

No se requiere `terraform init`, acceso a AWS ni un layer compilado. El perfil
`iac` parsea todos los `.tf` de las tres raices versionadas con python-hcl2 y corre
`terraform fmt -check`. Esto comprueba sintaxis y formato, **no** esquemas de
providers, seguridad IAM, `terraform validate`, plan ni viabilidad del despliegue.
Checkov sigue siendo una herramienta adicional descrita en `audit-pipeline/TESTING.md`;
no se incorpora como gate ni se ocultan sus hallazgos existentes.

## Usar el comando unico

```powershell
python scripts/verify.py --list
python scripts/verify.py pipeline
python scripts/verify.py api desktop
python scripts/verify.py
```

Usar el Python del entorno elegido; si ya existe `.venv-gui`, puede usarse su
ejecutable despues de instalar las herramientas faltantes. El runner usa ese mismo
interprete para todas las comprobaciones Python y el directorio propio de cada
componente. No requiere activar el entorno ni modifica fuentes para corregir errores.

| Perfil | Controles |
| --- | --- |
| `harness` | Tests del runner y lint de scripts |
| `pipeline` | Suite Lambda y Ruff con configuracion del pipeline |
| `api` | Suite HTTP/SQLite/S3 mock y lint con reglas base del escritorio |
| `desktop` | Suite de dominio, almacenamiento, UI offscreen y Ruff |
| `iac` | Parseo HCL y formato de las tres raices Terraform versionadas |

La copia Python `lambda/` raiz no tiene suite propia y no queda cubierta por
`pipeline`. Esta es una brecha registrada, no una cobertura implicita.

Los procesos reciben credenciales AWS ficticias, archivos de configuracion vacios
y metadata EC2 deshabilitada; el runner no lee `.env`. Los tests actuales mockean
AWS/FortiGate/modelo; la API usa HTTP real en loopback. Este entorno no es un
firewall ni una garantia de aislamiento de futuras pruebas: las llamadas externas
deben seguir sustituyendose por mocks.

## Resultado y evidencia

Cada control tiene limite de 180 segundos (`--timeout` permite ajustarlo). Un fallo,
timeout o herramienta no disponible produce salida global 1 y se ejecutan los demas
controles. Un perfil invalido produce salida 2. No hay controles omitidos por falta
de dependencias que se conviertan en aprobados.

El resumen JSON y logs quedan en `.harness/reports/` (ignorado por Git). Se pueden
separar ejecuciones con `--report-dir ruta`. Cada ejecucion reemplaza su resumen y
logs con los mismos nombres. Guardar un directorio distinto si se necesita historial.
El JSON registra plataforma, Python, comandos, tiempos, estado y codigos de salida;
los logs conservan detalle de pytest, incluidos skips.

CI usa los mismos perfiles, pipeline en Linux/Python 3.12 y desktop en Windows/Python
3.11. Linux ejecuta la prueba real `SIGALRM` que Windows omite. Se ejecuta en PRs,
push a main/master y manualmente; publica evidencia incluso ante fallos. Para que
impida merges hay que configurar required checks en las reglas de la rama de GitHub.

## Criterio de terminado de un cambio

1. Identificar fuentes y contratos afectados con `ARCHITECTURE.md` y los AGENTS.md.
2. Hacer un cambio acotado con verificaciones relevantes.
3. Ejecutar los perfiles afectados; si cambia el harness, incluir `harness`.
4. Revisar el JSON/logs y reportar fallos, skips y lo que no quedo demostrado.
5. Actualizar documentacion cuando cambien flujos o comandos.

La evidencia inicial y sus limites estan en `BASELINE.md`. La siguiente entrega
puede agregar evaluaciones semanticas del modelo y reglas automaticas de arquitectura.
