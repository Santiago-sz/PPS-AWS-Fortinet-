# P-001 · Definición del proyecto

Versión 2, presentada el 21 de noviembre de 2026. Aprobación y carga pendientes. Se revisó el cuerpo del capítulo I, incluida la tabla 1, en la pestaña t.0 del [informe](https://docs.google.com/document/d/1Xe4F3dk1vfgj5ROYR11ACfVK3YQc-43Za8wE-QnbIDA/edit?tab=t.0). La evaluación se refiere al contenido. La comprobación de la portadilla y la paginación queda para la revisión formal.

## Diagnóstico

| Requisito | Ubicación y estado | Fundamento y cambio propuesto |
|---|---|---|
| R-01-01 Origen | I.I · Parcial | El relato identifica las PPS en ZConsulting, la propuesta de Sergio Lapertosa y la incorporación del segundo integrante. Conservar ese antecedente. Falta explicar cómo se delimitó el prototipo. Una referencia general de AWS no acredita un vínculo comercial o institucional concreto. |
| R-01-02 Misión, visión y objetivos | I.II · Parcial | Los cinco objetivos incluyen respuesta automática, Access Analyzer y monitoreo continuo. Reformular los objetivos alrededor de los entregables verificables. Conservar la adopción regional como aspiración. |
| R-01-03 Necesidad | I.III · Parcial | Se reconoce el esfuerzo manual. Precisar qué debe resolver el auditor al pasar de una cláusula a la evidencia. Revisar también las tres respuestas del Golden Circle, donde reaparece la corrección automática. |
| R-01-04 ODS y diferenciales | I.IV y tabla 1 · Parcial | Se explican cuatro asociaciones. La reducción de esfuerzo y la alianza requieren respaldo. La tabla atribuye remediación autónoma, mapeo NIST/ISO y un puntaje global al producto. Sustituir esas filas por capacidades trazables. |
| R-01-05 Descripción breve | I.V, descripción general · Parcial | Hay una presentación general, pero promete supervisar consumo y recursos ociosos. Identificar usuario, entrada, equipo auditado y resultado. |
| R-01-06 Descripción detallada | I.V, descripción funcional · Parcial | La secuencia describe supervisión cloud y acciones correctivas. Reescribir el recorrido de una normativa y las condiciones necesarias para obtener un resultado. |

La [ficha reglamentaria](../requisitos/01-definicion-del-proyecto.md) recoge el art. 24.3.1. El contraste técnico toma como referencia el capítulo IX y el repositorio en `b262cff`, en particular el [generador](../../audit-engine/generator/handler_generator.py), el [ejecutor](../../audit-engine/executor/handler_executor.py) y el [registro de validación local](../../docs/context/handoffs/2026-11-15-local-functional-validation.md). Ese registro acredita el recorrido GUI/API con resultados sintéticos. La validación completa con el equipo institucional figura pendiente en el informe consultado.

## Texto propuesto para revisión

**I.I. Origen del proyecto.** La iniciativa surge durante las Prácticas Profesionales Supervisadas de Ingeniería en Sistemas de Información. En ZConsulting, Jorge Santiago Suarez trabaja bajo la supervisión del ingeniero Sergio Lapertosa, quien propone explorar la automatización de la seguridad en entornos cloud. En el segundo cuatrimestre se incorpora Santiago Guglielmone. El planteo inicial contempla la postura de seguridad en AWS y la gobernanza de identidades. El desarrollo de PostureGuard concentra ese interés en una tarea que los equipos de redes y auditoría pueden examinar control por control: evaluar la configuración de un firewall FortiGate frente a una normativa. El ámbito universitario aporta el contexto previsto para la validación institucional.

**I.II. Misión, visión y objetivos.** La misión de PostureGuard es facilitar la revisión de configuraciones FortiGate mediante informes que permiten rastrear cada hallazgo hasta la cláusula que lo origina. Su visión es que equipos de redes y auditoría de instituciones con normativas propias puedan reutilizar este método y revisar sus resultados de manera independiente.

El objetivo general es desarrollar un prototipo que audite la configuración de un firewall FortiGate frente a una normativa mediante consultas con permisos de solo lectura y presente los hallazgos con su evidencia y las propuestas de remediación correspondientes. La auditoría concluye con la entrega de las recomendaciones al responsable del equipo. Los objetivos específicos son:

1. Extraer del documento los controles verificables y conservar su referencia normativa.
2. Generar un script de auditoría y validar las operaciones que puede realizar.
3. Consultar la configuración mediante operaciones de lectura autorizadas y registrar la evidencia disponible para cada control.
4. Presentar los hallazgos y las recomendaciones de remediación en un informe que el operador pueda consultar y exportar.

**I.III. Necesidad a la que responde.** Una cláusula expresa una condición que la organización espera cumplir. Para evaluarla, el auditor debe identificar qué dato de configuración permite comprobarla, obtener ese dato e interpretar el resultado. El problema técnico consiste en formular una consulta pertinente y acotada. El problema organizacional consiste en conservar la relación entre la cláusula, el dato observado y el juicio emitido, de modo que otra persona pueda revisar la conclusión. Cuando falta evidencia, el informe debe hacer visible esa limitación.

En términos del Golden Circle, el **propósito** es facilitar la revisión de cada conclusión de auditoría. El **método** vincula cláusulas con verificaciones restringidas a consultas de lectura. El **producto** es una aplicación que recibe la normativa y presenta un informe con los controles evaluados, la evidencia y las acciones sugeridas.

**I.IV. ODS asociados y diferenciales.** El vínculo con el ODS 9 se encuentra en el desarrollo de una herramienta para inspeccionar infraestructura de red. El vínculo con el ODS 16 se plantea desde la rendición de cuentas: quien revisa una conclusión puede identificar el criterio utilizado y la evidencia que la sustenta. Respecto del ODS 8, la automatización de consultas repetitivas busca liberar tiempo para interpretar hallazgos. Evaluar ese beneficio requiere comparar el esfuerzo de una auditoría manual con el del flujo asistido. El origen en las prácticas profesionales ofrece un contexto para analizar el ODS 17. El alcance de una colaboración institucional requiere confirmación de los autores.

*Tabla 1. Diferenciales del proyecto.*

| Característica | Manifestación en PostureGuard |
|---|---|
| Normativa como entrada | El operador aporta el documento del que se extraen los controles. |
| Trazabilidad por control | El hallazgo reúne la referencia a la cláusula y la evidencia disponible. |
| Ejecución restringida | El ejecutor comprueba la integridad del script, repite su validación y limita las consultas al catálogo autorizado. |
| Revisión humana | El informe presenta la remediación propuesta para que el responsable evalúe su pertinencia. |

**I.V. Descripción general del sistema.** PostureGuard asiste al personal de redes y auditoría en la evaluación de un firewall FortiGate. Recibe una normativa en PDF o DOCX con texto extraíble y produce un informe que permite revisar qué se evaluó, con qué criterio y qué evidencia sustenta cada hallazgo.

**Descripción funcional.** El operador carga la normativa mediante la aplicación de escritorio. La API local conserva el documento y un puente permite enviarlo al procesamiento en AWS. El generador extrae el texto y utiliza Amazon Bedrock para identificar controles y generar un script de auditoría. Tras validar el script, guarda los artefactos necesarios para la ejecución.

Cuando se habilita la ejecución, el ejecutor comprueba la integridad del script y repite su validación. El entorno restringido permite consultar la API del FortiGate mediante operaciones GET del catálogo autorizado. El informe asocia los resultados con sus cláusulas y recoge las recomendaciones que corresponden. Una vez sincronizado el resultado, el operador puede consultarlo desde la aplicación y exportarlo en JSON o Markdown.

## Decisiones para el autor

El autor confirma la auditoría de FortiGate con permisos de solo lectura y propuestas de remediación como alcance del proyecto. Queda por confirmar si «ENTIDAD» es la denominación que debe conservarse. El relato de las PPS procede del borrador de los autores. Confirmar los aportes institucionales antes de describir una alianza bajo el ODS 17. Al aprobar una versión, revisar las citas vinculadas a los pasajes sustituidos y su correspondencia con la bibliografía. El resumen y el capítulo III quedan como referencias cruzadas para una revisión posterior.
