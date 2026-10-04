#!/bin/sh
valkey-server --daemonize yes
uv run celery -A app.celery_app worker  -f celery.log --loglevel=INFO -E --detach
exec uv run gunicorn -b 0.0.0.0:5000 app.routes:flask_app --reload --access-logfile - --error-logfile - --graceful-timeout 1200 --timeout 1200
