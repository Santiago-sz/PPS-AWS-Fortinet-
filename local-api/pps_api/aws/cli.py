"""Operaciones CLI AWS; importación del SDK solo al invocarlas."""

from pathlib import Path


def run(args, service, parser):
    import boto3
    from botocore.config import Config

    from .bridge import Bridge
    from .config import aws_options, load_settings

    try:
        if args.env_file != Path(".env") and not args.env_file.is_file():
            raise ValueError("No existe el archivo indicado en --env-file.")
        settings = load_settings(args.env_file)
        options, policies, reports = aws_options(
            settings, args.policies_bucket, args.reports_bucket
        )
        executor = args.executor_function or settings.get("PPS_EXECUTOR_FUNCTION")
        if args.action == "approve" and not args.run_id:
            raise ValueError("Indicá el run_id a aprobar: aws approve RUN_ID.")
        if args.action == "approve" and not executor:
            raise ValueError("Indicá --executor-function o completá PPS_EXECUTOR_FUNCTION en .env.")
        if args.action != "approve" and args.run_id:
            raise ValueError("run_id solo se acepta con la acción approve.")
    except ValueError as exc:
        parser.error(str(exc))
    session = boto3.Session(**options)
    no_retry = Config(retries={"total_max_attempts": 1})
    s3 = session.client("s3", config=no_retry)
    worker = Bridge(service, s3, policies, reports)
    if args.action == "approve":
        # Una sola invocación asíncrona; un reintento duplicaría la ejecución.
        executor_client = session.client("lambda", config=no_retry)
        status = worker.approve(args.run_id, executor, executor_client)
        print(f"Ejecutor invocado para {args.run_id} (StatusCode {status}). Luego: aws sync.")
    elif args.action == "list-pending":
        pending = worker.list_pending()
        print("\n".join(pending) if pending else "Sin ejecuciones pendientes.")
    else:
        print(f"Auditorías procesadas: {getattr(worker, args.action)()}")
