import argparse
import json
from pathlib import Path

from .services import Service


def main():
    parser = argparse.ArgumentParser(description="API PPS de desarrollo (solo loopback)")
    parser.add_argument("--database", default=".pps-api/development.sqlite3")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--tls-cert", type=Path)
    serve.add_argument("--tls-key", type=Path)
    ingest = commands.add_parser(
        "import-result", help="Adjuntar artefactos reales a una auditoría local"
    )
    ingest.add_argument("audit_id")
    ingest.add_argument("manifest", type=Path)
    ingest.add_argument("report", type=Path)
    bridge = commands.add_parser(
        "aws", help="Enviar a S3 o recuperar reportes (requiere credenciales AWS)"
    )
    bridge.add_argument("action", choices=["dispatch", "sync", "list-pending", "approve"])
    bridge.add_argument("run_id", nargs="?", help="run_id a aprobar (solo para approve)")
    bridge.add_argument("--policies-bucket")
    bridge.add_argument("--reports-bucket")
    bridge.add_argument(
        "--executor-function",
        help="Nombre o ARN de la Lambda ejecutora (o PPS_EXECUTOR_FUNCTION en .env)",
    )
    args = parser.parse_args()
    if args.command == "serve" and bool(args.tls_cert) != bool(args.tls_key):
        parser.error("HTTPS requiere --tls-cert y --tls-key juntos.")
    service = Service(args.database)
    if args.command == "serve":
        from .server import create_server

        server = create_server(service, args.port, tls_cert=args.tls_cert, tls_key=args.tls_key)
        print(
            f"API de desarrollo: {server.scheme}://127.0.0.1:{server.server_port} (sin OIDC)",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    elif args.command == "import-result":
        service.finish(
            args.audit_id,
            json.loads(args.manifest.read_text(encoding="utf-8")),
            json.loads(args.report.read_text(encoding="utf-8")),
        )
        print("Reporte asociado.")
    else:
        from .aws.cli import run

        run(args, service, parser)


if __name__ == "__main__":
    main()
