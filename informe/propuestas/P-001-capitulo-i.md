# P-001 · Definición del proyecto

Versión 6, presentada el 21 de noviembre de 2026. Aprobación y carga pendientes. Se revisó el cuerpo del capítulo I, incluida la tabla 1, en la pestaña t.0 del [informe académico](https://docs.google.com/document/d/1Xe4F3dk1vfgj5ROYR11ACfVK3YQc-43Za8wE-QnbIDA/edit?tab=t.0). La evaluación se refiere al contenido. La comprobación de la portadilla y la paginación queda para la revisión formal.

## Estado de los seis requisitos de contenido

La versión 6 cubre los seis requisitos en el texto propuesto y está pendiente de aprobación y carga. La columna de Google Docs conserva el diagnóstico de la lectura inicial del 21 de noviembre.

| Requisito | Google Docs al revisar | Cobertura en la propuesta v6 | Fundamento del diagnóstico inicial |
|---|---|---|---|
| R-01-01 Origen | I.I · Parcial | Cubierto | El relato identifica las PPS en ZConsulting, la propuesta de Sergio Lapertosa y la incorporación del segundo integrante. Conservar ese antecedente. Falta explicar cómo se delimitó el prototipo. Una referencia general de AWS no acredita un vínculo comercial o institucional concreto. |
| R-01-02 Misión, visión y objetivos | I.II · Parcial | Cubierto | Los cinco objetivos incluyen respuesta automática, Access Analyzer y monitoreo continuo. Reformular los objetivos alrededor de los entregables verificables. Conservar la adopción regional como aspiración. |
| R-01-03 Necesidad | I.III · Parcial | Cubierto | Se reconoce el esfuerzo manual. Precisar qué debe resolver el auditor al pasar de una cláusula a la evidencia. Revisar también las tres respuestas del Golden Circle, donde reaparece la corrección automática. |
| R-01-04 ODS y diferenciales | I.IV y tabla 1 · Parcial | Cubierto | Se explican cuatro asociaciones. La reducción de esfuerzo y la alianza requieren respaldo. La tabla atribuye remediación autónoma, mapeo NIST/ISO y un puntaje global al producto. Sustituir esas filas por capacidades trazables. |
| R-01-05 Descripción breve | I.V, descripción general · Parcial | Cubierto | Hay una presentación general, pero promete supervisar consumo y recursos ociosos. Identificar usuario, entrada, equipo auditado y resultado. |
| R-01-06 Descripción detallada | I.V, descripción funcional · Parcial | Cubierto | La secuencia describe supervisión cloud y acciones correctivas. Reescribir el recorrido de una normativa y las condiciones necesarias para obtener un resultado. |

La [ficha reglamentaria](../requisitos/01-definicion-del-proyecto.md) recoge el art. 24.3.1. El contraste técnico toma como referencia el capítulo IX y el repositorio en `b262cff`, en particular el [generador](../../audit-engine/generator/handler_generator.py), el [ejecutor](../../audit-engine/executor/handler_executor.py) y el [registro de validación local](../../docs/context/handoffs/2026-11-15-local-functional-validation.md). Ese registro acredita el recorrido GUI/API con resultados sintéticos. La validación completa con el equipo institucional figura pendiente en el informe académico consultado.

## Texto propuesto para revisión

**I.I. Origen del proyecto.** En 2026, durante las Prácticas Profesionales Supervisadas de Ingeniería en Sistemas de Información en ZConsulting, Jorge Santiago Suarez trabaja bajo la supervisión del ingeniero Sergio Lapertosa. Allí surge la idea de automatizar tareas de seguridad en AWS y se desarrollan los primeros conceptos del proyecto. En el segundo cuatrimestre, Santiago Guglielmone se incorpora al proyecto desde fuera de ZConsulting.

La incorporación de la generación aumentada por recuperación (RAG) lleva al equipo a concentrar el proyecto en FortiGate. Al trabajar con una sola familia de equipos, se puede reunir documentación técnica específica y recuperar los fragmentos pertinentes para cada control. La normativa de la organización establece qué condición se evalúa. La documentación técnica orienta la forma de comprobarla en el firewall. Una institución pública facilita las herramientas FortiGate para realizar pruebas en un entorno real.

**I.II. Misión, visión y objetivos.** La misión de PostureGuard es facilitar la revisión de configuraciones FortiGate mediante reportes que permiten rastrear cada hallazgo hasta la cláusula que lo origina. Su visión es que equipos de redes y ciberseguridad de instituciones del nordeste argentino con normativas propias puedan reutilizar este método y revisar sus resultados de manera independiente.

El objetivo general es desarrollar un prototipo para auditar la configuración de un firewall FortiGate frente a una normativa mediante consultas con permisos de solo lectura. La auditoría produce un reporte con los controles evaluados, el resultado de cada verificación, la evidencia disponible y, cuando corresponde, propuestas de remediación. Para alcanzar este objetivo se plantean cuatro objetivos específicos.

1. Extraer del documento los controles verificables y conservar su referencia normativa.
2. Generar un script de auditoría y validar las operaciones que puede realizar.
3. Consultar la configuración mediante operaciones de lectura autorizadas y registrar la evidencia disponible para cada control.
4. Presentar los hallazgos en un reporte que el operador pueda consultar y exportar, con recomendaciones de remediación cuando correspondan.

**I.III. Necesidad a la que responde.** En la institución pública, el personal de redes y de ciberseguridad verifica si las políticas configuradas en el firewall satisfacen una condición determinada. Como los nombres de las políticas carecen de una convención uniforme, el nombre por sí solo resulta insuficiente para identificar la regla pertinente. El personal debe recorrer las políticas y examinar su configuración. Por ejemplo, para comprobar una restricción de acceso entre dos redes, el equipo examina el origen, el destino, el servicio y la acción de las reglas pertinentes. Una regla ya definida puede pasar inadvertida durante esa búsqueda.

Cuando la revisión abarca varias políticas, el equipo repite ese trabajo para cada condición. La necesidad consiste en localizar la evidencia pertinente y conservar el vínculo entre la cláusula evaluada, la configuración observada y el hallazgo. Esa relación permite al responsable revisar el fundamento del resultado. Si la evidencia resulta insuficiente, el control puede quedar indeterminado.

En el *Golden Circle*, el **propósito** es que el equipo pueda fundamentar si se cumple una condición de seguridad. El **método** consiste en traducir la cláusula en una verificación de solo lectura y conservar la evidencia observada. El **producto** es un reporte de auditoría que el responsable puede revisar y compartir.

**I.IV. Objetivos de Desarrollo Sostenible (ODS) asociados y diferenciales.** El proyecto se vincula con cuatro objetivos de la Agenda 2030 (Programa de las Naciones Unidas para el Desarrollo, s. f.).

**ODS 9 — Industria, innovación e infraestructura.** Este objetivo promueve la innovación y el desarrollo de infraestructuras resilientes. PostureGuard aporta una herramienta para inspeccionar la configuración de un componente de la infraestructura de red, el firewall FortiGate, y documentar las condiciones observadas.

**ODS 16 — Paz, justicia e instituciones sólidas.** Entre sus metas se encuentra la rendición de cuentas de las instituciones. En una auditoría con PostureGuard, el personal de la institución pública puede revisar qué cláusula motiva cada hallazgo y qué evidencia respalda la conclusión.

**ODS 8 — Trabajo decente y crecimiento económico.** Este objetivo contempla la mejora de la productividad mediante la innovación tecnológica. La automatización de consultas repetitivas busca que el personal de redes y ciberseguridad pueda dedicar más tiempo a interpretar los hallazgos. Para evaluar ese beneficio se requiere comparar el esfuerzo de una auditoría manual con el del recorrido asistido.

**ODS 17 — Alianzas para lograr los objetivos.** Este objetivo promueve la cooperación y el intercambio de conocimientos y recursos. En el proyecto, ZConsulting brinda el ámbito para formular el tema y desarrollar sus primeros conceptos. La institución pública facilita las herramientas FortiGate que permiten realizar las pruebas en un contexto real.

La tabla 1 resume los aportes de PostureGuard respecto del procedimiento de revisión manual descrito en I.III.

*Tabla 1. Diferenciales de PostureGuard en la revisión de configuraciones FortiGate.*

| Diferencial | Cómo se manifiesta en PostureGuard | Qué aporta al personal de redes y ciberseguridad |
|---|---|---|
| Auditoría guiada por la normativa | A partir de una normativa en PDF o DOCX, el sistema identifica controles verificables y genera consultas sobre la configuración del firewall. | El punto de partida es la condición que se necesita comprobar. Esto resulta especialmente útil cuando el nombre de una política aporta poca información sobre su función. |
| Trazabilidad entre cláusula, evidencia y hallazgo | El reporte vincula el resultado de cada control con la cláusula de origen y la evidencia disponible. | El operador puede fundamentar una observación y otra persona puede revisar cómo se llegó a esa conclusión. |
| Verificación con permisos de solo lectura | El ejecutor consulta la configuración del FortiGate mediante operaciones de lectura autorizadas. | El equipo puede auditar el dispositivo conservando su configuración durante la verificación. |
| Propuestas de remediación por hallazgo | Cuando corresponde, el reporte incluye una recomendación asociada al hallazgo. | El responsable cuenta con una acción concreta para evaluar y conserva la decisión sobre si corresponde aplicarla. |

**I.V. Descripción general del sistema.** PostureGuard asiste al personal de redes y ciberseguridad en la evaluación de un firewall FortiGate. Recibe una normativa en PDF o DOCX con texto extraíble y produce un reporte que permite revisar qué se evaluó, con qué criterio y qué evidencia sustenta cada hallazgo.

**Descripción funcional.** El operador carga la normativa desde la aplicación de escritorio. La API local conserva el documento y un componente de integración lo envía a AWS. El generador extrae el texto e identifica los controles verificables con Amazon Bedrock. El diseño con RAG prevé que, cuando la base de conocimientos está habilitada, el generador recupere referencias técnicas a partir del título y el propósito de cada control. Esas referencias sirven de contexto al generar el script de auditoría. Una vez validado, se guarda el script junto con los datos necesarios para comprobar su integridad y ejecutarlo.

Cuando se habilita la ejecución, el ejecutor comprueba la integridad del script y repite su validación. El entorno restringido permite consultar la API del FortiGate mediante operaciones GET del catálogo autorizado. El reporte asocia los resultados con sus cláusulas y recoge las recomendaciones que corresponden. Una vez sincronizado el resultado, el operador puede consultarlo desde la aplicación y exportarlo en JSON o Markdown.

## Fuente de los antecedentes y estado de revisión

Referencia para la bibliografía del informe académico: Programa de las Naciones Unidas para el Desarrollo. (s. f.). *Objetivos de Desarrollo Sostenible*. https://www.undp.org/es/sustainable-development-goals

El uso opcional de referencias por control está documentado en la [decisión 11 del proyecto](https://github.com/Santiago-sz/PPS-AWS-Fortinet-/blob/2927b58/docs/context/decisions/11-referencias-en-generacion.md).

El autor confirmó en esta revisión la cronología de 2026, el motivo de la delimitación, el procedimiento de búsqueda de políticas y la contribución de cada organización. Se adoptó «institución pública» como denominación anónima. El desarrollo del RAG cuenta además con una [decisión técnica registrada en la revisión 2927b58](https://github.com/Santiago-sz/PPS-AWS-Fortinet-/blob/2927b58/docs/context/decisions/10-bedrock-knowledge-base.md). Las pruebas en contexto real se consignan según el testimonio del autor. La comprobación del recorrido completo requiere su propio registro de ejecución. La versión 6 queda presentada para aprobación editorial.
