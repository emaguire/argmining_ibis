#!/bin/sh
source venv/bin/activate
exec gunicorn -b :5000 --access-logfile - --error-logfile - app --graceful-timeout 1200 --timeout 1200
