# Documentación del proyecto

- [Contexto para agentes](context/README.md): primera iteración del conocimiento
  del proyecto, rutas de consulta y continuidad de tareas.
- [Documentación base](base/README.md): documentación operativa y de diseño
  preexistente, con sus diagramas. Se conserva sin cambios de contenido.

Los manuales específicos permanecen junto a sus componentes:
[verificación](../audit-engine/TESTING.md),
[secretos](../audit-engine/SECRETS.md),
[evals](../audit-engine/evals/README.md),
[API](../local-api/README.md) y [desktop](../gui/README.md).

Las rutas `docs/01…07` y `docs/diagrams/` mencionadas en la documentación base
corresponden ahora a `docs/base/01…07` y `docs/base/diagrams/`. Las referencias
a archivos del repositorio escritas entre comillas de código son relativas a
la raíz del repositorio, salvo indicación explícita. Los enlaces y las imágenes
relativos entre documentos base conservan su estructura.

El contrato de trabajo sigue siendo [AGENTS.md](../AGENTS.md). La organización
del contexto no instala hooks ni incorpora cambios al generador o al sandbox.
