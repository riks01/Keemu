"""
Celery application instance and configuration.
"""

from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

# Create Celery application
celery_app = Celery(
    "keemu",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Configure Celery
celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=settings.celery_accept_content_list,
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=settings.CELERY_ENABLE_UTC,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    result_expires=3600,  # 1 hour
)

# Celery Beat Schedule (Periodic Tasks)
celery_app.conf.beat_schedule = {
    'fetch-youtube-content': {
        'task': 'youtube.fetch_all_active_channels',
        'schedule': crontab(minute='0', hour=f'*/{settings.YOUTUBE_CHECK_INTERVAL_HOURS}'),
        'options': {'queue': 'youtube'},
    },
    'fetch-reddit-discovery': {
        'task': 'reddit.fetch_all_active_channels',
        'schedule': crontab(minute='0', hour='*/3'),  # Every 3 hours (smart strategy)
        'options': {'queue': 'reddit'},
    },
    'fetch-blog-content': {
        'task': 'blog.fetch_all_active_blogs',
        'schedule': crontab(minute='0', hour='*/12'),  # Every 12 hours
        'options': {'queue': 'blog'},
    },
    'get-processing-stats': {
        'task': 'youtube.get_processing_stats',
        'schedule': crontab(minute='*/15'),  # Every 15 minutes
        'options': {'queue': 'monitoring'},
    },
}

# Task routing
celery_app.conf.task_routes = {
    'youtube.*': {'queue': 'youtube'},
    'reddit.*': {'queue': 'reddit'},
    'blog.*': {'queue': 'blog'},
}

# Auto-discover tasks from app.tasks
celery_app.autodiscover_tasks(['app.tasks'])
