#!/bin/sh
rabbitmq-server -detached
redis-server --daemonize yes
celery -A app.celery_tasks worker --loglevel=INFO --detach
exec gunicorn -b 0.0.0.0:5000 app.routes:flask_app  --reload --access-logfile - --error-logfile - --graceful-timeout 1200 --timeout 1200
