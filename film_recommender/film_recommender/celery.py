import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'film_recommender.settings')

app = Celery('film_recommender')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

def setup_celery():
    """Setup Celery configuration"""


    # Встановлюємо Django settings перед імпортом Django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'film_recommender.settings')

    # Ініціалізуємо Django (важливо для правильної роботи)
    import django
    django.setup()

    app = Celery('film_recommender')
    app.config_from_object('django.conf:settings', namespace='CELERY')
    app.autodiscover_tasks()

    # Налаштування періодичних задач
    app.conf.beat_schedule = {
        'import-movies-every-week': {
            'task': 'recommender.tasks.import_popular_movies_task',
            'schedule': crontab(hour=3, minute=0, day_of_week=0),  # Кожної неділі о 3:00
            'args': (50,),
            'options': {
                'queue': 'default',
                'retry': True,
                'retry_policy': {
                    'max_retries': 3,
                    'interval_start': 0,
                    'interval_step': 0.2,
                    'interval_max': 0.2,
                }
            }
        },
        'generate-recommendations-daily': {
            'task': 'recommender.tasks.generate_recommendations_task',
            'schedule': crontab(hour=4, minute=0),  # Кожного дня о 4:00
            'args': (None, True,),
            'options': {
                'queue': 'default',
                'retry': True,
                'retry_policy': {
                    'max_retries': 2,
                    'interval_start': 0,
                    'interval_step': 0.5,
                    'interval_max': 1.0,
                }
            }
        },
    }

    # Додаткові налаштування для beat
    app.conf.update(
        timezone='Europe/Kiev',  # Встановіть ваш часовий пояс
        enable_utc=True,
        beat_scheduler='django_celery_beat.schedulers:DatabaseScheduler',  # Якщо використовуєте django-celery-beat
    )

    return app