import argparse
import json
from pathlib import Path

from .service import Service


def main():
    parser = argparse.ArgumentParser(description="API PPS de desarrollo (solo loopback)")
    parser.add_argument("--database", default=".pps-api/development.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    ingest = commands.add_parser(
        "import-result", help="Adjuntar artefactos reales a una auditoría local"
    )
    ingest.add_argument("audit_id")
    ingest.add_argument("manifest", type=Path)
    ingest.add_argument("report", type=Path)
    bridge = commands.add_parser(
        "aws", help="Enviar a S3 o recuperar reportes (requiere credenciales AWS)"
    )
    bridge.add_argument("action", choices=["dispatch", "sync"])
    bridge.add_argument("--policies-bucket", required=True)
    bridge.add_argument("--reports-bucket", required=True)
    args = parser.parse_args()
    service = Service(args.database)
    if args.command == "serve":
        from .server import create_server

        server = create_server(service, args.port)
        print(f"API de desarrollo: http://127.0.0.1:{server.server_port} (sin OIDC)", flush=True)
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
        import boto3
        from botocore.config import Config

        from .aws_bridge import Bridge

        s3 = boto3.client("s3", config=Config(retries={"total_max_attempts": 1}))
        worker = Bridge(service, s3, args.policies_bucket, args.reports_bucket)
        print(f"Auditorías procesadas: {getattr(worker, args.action)()}")


if __name__ == "__main__":
    main()
