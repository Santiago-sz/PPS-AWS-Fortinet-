# API local

- Es un servicio local de desarrollo en loopback, con SQLite. No representa un
  servicio multiusuario autenticado ni debe ampliar su escucha como atajo.
- Respetar `../../desktop/API_CONTRACT.md`, integridad de cargas, idempotencia,
  inmutabilidad de resultados y correlacion audit_id/run_id/policy_key.
- La carga HTTP no envia documentos a AWS. Mantener explicitos dispatch y sync;
  no ejecutarlos para verificar cambios.
- Ejecutar el perfil `api` y tambien `desktop` si cambia el contrato o sus estados.
  Las pruebas de API permiten HTTP real exclusivamente en loopback.
