"""WSGI entrypoint para gunicorn."""
import os
from app import create_app
from app.harvest.scheduler import configure as configure_scheduler

app = create_app()

if os.environ.get("LEX_SCHEDULER", "1") == "1":
    try:
        configure_scheduler(app)
    except Exception as e:
        app.logger.warning("Falha ao iniciar scheduler: %s", e)
