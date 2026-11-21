# P-001 · Definición del proyecto

Versión 4, presentada el 21 de noviembre de 2026. Aprobación y carga pendientes. Se revisó el cuerpo del capítulo I, incluida la tabla 1, en la pestaña t.0 del [informe](https://docs.google.com/document/d/1Xe4F3dk1vfgj5ROYR11ACfVK3YQc-43Za8wE-QnbIDA/edit?tab=t.0). La evaluación se refiere al contenido. La comprobación de la portadilla y la paginación queda para la revisión formal.

## Estado de los seis requisitos de contenido

La versión 4 cubre los seis requisitos en el texto propuesto y está pendiente de aprobación y carga. La columna de Google Docs conserva el diagnóstico de la lectura inicial del 21 de noviembre.

| Requisito | Google Docs al revisar | Cobertura en la propuesta v4 | Fundamento del diagnóstico inicial |
|---|---|---|---|
| R-01-01 Origen | I.I · Parcial | Cubierto | El relato identifica las PPS en ZConsulting, la propuesta de Sergio Lapertosa y la incorporación del segundo integrante. Conservar ese antecedente. Falta explicar cómo se delimitó el prototipo. Una referencia general de AWS no acredita un vínculo comercial o institucional concreto. |
| R-01-02 Misión, visión y objetivos | I.II · Parcial | Cubierto | Los cinco objetivos incluyen respuesta automática, Access Analyzer y monitoreo continuo. Reformular los objetivos alrededor de los entregables verificables. Conservar la adopción regional como aspiración. |
| R-01-03 Necesidad | I.III · Parcial | Cubierto | Se reconoce el esfuerzo manual. Precisar qué debe resolver el auditor al pasar de una cláusula a la evidencia. Revisar también las tres respuestas del Golden Circle, donde reaparece la corrección automática. |
| R-01-04 ODS y diferenciales | I.IV y tabla 1 · Parcial | Cubierto | Se explican cuatro asociaciones. La reducción de esfuerzo y la alianza requieren respaldo. La tabla atribuye remediación autónoma, mapeo NIST/ISO y un puntaje global al producto. Sustituir esas filas por capacidades trazables. |
| R-01-05 Descripción breve | I.V, descripción general · Parcial | Cubierto | Hay una presentación general, pero promete supervisar consumo y recursos ociosos. Identificar usuario, entrada, equipo auditado y resultado. |
| R-01-06 Descripción detallada | I.V, descripción funcional · Parcial | Cubierto | La secuencia describe supervisión cloud y acciones correctivas. Reescribir el recorrido de una normativa y las condiciones necesarias para obtener un resultado. |

La [ficha reglamentaria](../requisitos/01-definicion-del-proyecto.md) recoge el art. 24.3.1. El contraste técnico toma como referencia el capítulo IX y el repositorio en `b262cff`, en particular el [generador](../../audit-engine/generator/handler_generator.py), el [ejecutor](../../audit-engine/executor/handler_executor.py) y el [registro de validación local](../../docs/context/handoffs/2026-11-15-local-functional-validation.md). Ese registro acredita el recorrido GUI/API con resultados sintéticos. La validación completa con el equipo institucional figura pendiente en el informe consultado.

## Texto propuesto para revisión

**I.I. Origen del proyecto.** En 2026, durante las Prácticas Profesionales Supervisadas de Ingeniería en Sistemas de Información en ZConsulting, Jorge Santiago Suarez trabaja bajo la supervisión del ingeniero Sergio Lapertosa. Allí surge la idea de automatizar tareas de seguridad en AWS y se desarrollan los primeros conceptos del proyecto. Santiago Guglielmone se incorpora en el segundo cuatrimestre.

La implementación de un sistema de generación aumentada por recuperación (RAG) lleva al equipo a acotar el problema. Este método permite recuperar material de referencia para aportar contexto al modelo. Al concentrarse en FortiGate, el equipo puede seleccionar documentación y posibles soluciones para una familia concreta de equipos y criterios de auditoría. Así se define el alcance de PostureGuard: auditar la configuración con permisos de solo lectura y formular propuestas de remediación. Una institución pública facilita las herramientas FortiGate con las que se realizan pruebas en un entorno real.

**I.II. Misión, visión y objetivos.** La misión de PostureGuard es facilitar la revisión de configuraciones FortiGate mediante reportes que permiten rastrear cada hallazgo hasta la cláusula que lo origina. Su visión es que equipos de redes y ciberseguridad de instituciones con normativas propias puedan reutilizar este método y revisar sus resultados de manera independiente.

El objetivo general es desarrollar un prototipo que audite la configuración de un firewall FortiGate frente a una normativa mediante consultas con permisos de solo lectura y presente los hallazgos con su evidencia y las propuestas de remediación correspondientes. La auditoría concluye con la entrega de las recomendaciones al responsable del equipo. Los objetivos específicos son:

1. Extraer del documento los controles verificables y conservar su referencia normativa.
2. Generar un script de auditoría y validar las operaciones que puede realizar.
3. Consultar la configuración mediante operaciones de lectura autorizadas y registrar la evidencia disponible para cada control.
4. Presentar los hallazgos y las recomendaciones de remediación en un reporte que el operador pueda consultar y exportar.

**I.III. Necesidad a la que responde.** En la institución pública, el personal de redes y de ciberseguridad verifica si las políticas configuradas en el firewall satisfacen una condición determinada. Como los nombres de las políticas carecen de una convención uniforme, el nombre por sí solo resulta insuficiente para identificar la regla pertinente. El personal debe recorrer las políticas y examinar su configuración. Una regla ya definida puede pasar inadvertida durante esa búsqueda.

Cuando la revisión abarca varias políticas, el equipo repite ese trabajo para cada condición. La necesidad consiste en localizar la evidencia pertinente y conservar el vínculo entre la cláusula evaluada, la configuración observada y el hallazgo. Esa relación permite al responsable revisar tanto el resultado como la recomendación que recibe.

En términos del Golden Circle, el **propósito** es facilitar la revisión de cada conclusión de auditoría. El **método** vincula cláusulas con verificaciones restringidas a consultas de lectura. El **producto** es una aplicación que recibe la normativa y presenta un reporte con los controles evaluados, la evidencia y las acciones sugeridas.

**I.IV. ODS asociados y diferenciales.** El vínculo con el ODS 9 se encuentra en el desarrollo de una herramienta para inspeccionar infraestructura de red. El vínculo con el ODS 16 se plantea desde la rendición de cuentas: quien revisa una conclusión puede identificar el criterio utilizado y la evidencia que la sustenta. Respecto del ODS 8, la automatización de consultas repetitivas busca liberar tiempo para interpretar hallazgos. Evaluar ese beneficio requiere comparar el esfuerzo de una auditoría manual con el del flujo asistido. La relación con el ODS 17 se fundamenta en los aportes que permiten llevar la idea a un contexto de prueba. ZConsulting brinda el ámbito para formular el tema y desarrollar sus primeros conceptos. La institución pública facilita las herramientas FortiGate para las pruebas.

*Tabla 1. Diferenciales del proyecto.*

| Característica | Manifestación en PostureGuard |
|---|---|
| Normativa como entrada | El operador aporta el documento del que se extraen los controles. |
| Trazabilidad por control | El hallazgo reúne la referencia a la cláusula y la evidencia disponible. |
| Ejecución restringida | El ejecutor comprueba la integridad del script, repite su validación y limita las consultas al catálogo autorizado. |
| Revisión humana | El reporte presenta la remediación propuesta para que el responsable evalúe su pertinencia. |

**I.V. Descripción general del sistema.** PostureGuard asiste al personal de redes y ciberseguridad en la evaluación de un firewall FortiGate. Recibe una normativa en PDF o DOCX con texto extraíble y produce un reporte que permite revisar qué se evaluó, con qué criterio y qué evidencia sustenta cada hallazgo.

**Descripción funcional.** El operador carga la normativa mediante la aplicación de escritorio. La API local conserva el documento y un puente permite enviarlo al procesamiento en AWS. El generador extrae el texto y utiliza Amazon Bedrock para identificar controles y generar un script de auditoría. Tras validar el script, guarda los artefactos necesarios para la ejecución.

Cuando se habilita la ejecución, el ejecutor comprueba la integridad del script y repite su validación. El entorno restringido permite consultar la API del FortiGate mediante operaciones GET del catálogo autorizado. El reporte asocia los resultados con sus cláusulas y recoge las recomendaciones que corresponden. Una vez sincronizado el resultado, el operador puede consultarlo desde la aplicación y exportarlo en JSON o Markdown.

## Fuente de los antecedentes y estado de revisión

El autor confirmó en esta revisión la cronología de 2026, el motivo de la delimitación, el procedimiento de búsqueda de políticas y la contribución de cada organización. Se adoptó «institución pública» como denominación anónima. El desarrollo del RAG cuenta además con una [decisión técnica registrada en la revisión 2927b58](https://github.com/Santiago-sz/PPS-AWS-Fortinet-/blob/2927b58/docs/context/decisions/10-bedrock-knowledge-base.md). Las pruebas en contexto real se consignan según el testimonio del autor. La comprobación del recorrido completo requiere su propio registro de ejecución. La versión 4 queda presentada para aprobación editorial.
