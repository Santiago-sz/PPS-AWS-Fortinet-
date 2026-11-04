# PPS AWS / Fortinet

Auditorias de configuracion FortiGate basadas en politicas, con pipeline AWS,
API local de desarrollo y escritorio PySide6.

- [Mapa de fuentes y arquitectura](docs/ARCHITECTURE.md)
- [Agentes del pipeline: roles, carga y limites](docs/AGENTS_RUNTIME.md)
- [Preparacion y comando de verificacion](docs/HARNESS.md)
- [Linea base de la primera entrega](docs/BASELINE.md)
- [Escritorio](desktop/README.md) y [API local](audit-pipeline/api/README.md)
- [Pruebas del pipeline y herramientas adicionales](audit-pipeline/TESTING.md)

Con las dependencias instaladas: `python scripts/verify.py`.
Para un componente: `python scripts/verify.py pipeline` (tambien `api`, `desktop`,
`iac`, `harness`). El comando no despliega infraestructura ni ejecuta auditorias reales.
