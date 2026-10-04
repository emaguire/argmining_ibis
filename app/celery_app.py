# celery_app.py
from celery import Celery

celery_app = Celery("celery_app")
celery_app.config_from_object({
    "broker_url": "valkey://localhost:6379/0",
    "result_backend": "valkey://localhost:6379/1",
    # "include": ["tasks"],
})