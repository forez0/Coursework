import multiprocessing
import os
import sys
from celery import Celery

# Встановлюємо перемінну оточення для Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'film_recommender.settings')

# Ініціалізація Celery
app = Celery('film_recommender')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

if __name__ == '__main__':
    # Для Windows може знадобитися spawn метод
    if sys.platform.startswith('win'):
        multiprocessing.set_start_method('spawn', force=True)

    # Запуск воркера з передачею аргументів командного рядка
    try:
        app.worker_main(sys.argv[1:])
    except KeyboardInterrupt:
        print("Worker stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Worker error: {e}")
        sys.exit(1)