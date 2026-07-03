"""Entry point para `python -m app.main` ou `flask --app app.main run`."""
import os
from . import create_app
from .harvest.scheduler import configure as configure_scheduler

app = create_app()

if os.environ.get("LEX_SCHEDULER", "1") == "1":
    try:
        configure_scheduler(app)
    except Exception as e:
        app.logger.warning("Falha ao iniciar scheduler: %s", e)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
