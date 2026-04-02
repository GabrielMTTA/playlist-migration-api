from celery import Celery

from app.core.config import settings

celery = Celery(
    "playlist_worker",
    broker=settings.get_celery_broker_url(),
    backend=settings.get_celery_result_backend(),
)

celery.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Reliability: tasks acknowledged only after completion
    task_acks_late=True,
    # Worker prefetches 1 task at a time (fair scheduling)
    worker_prefetch_multiplier=1,
    # Result expiry: 1 hour
    result_expires=3600,
    # Rate limiting default per task
    task_default_rate_limit="10/s",
)

celery.autodiscover_tasks(["app.workers"])
