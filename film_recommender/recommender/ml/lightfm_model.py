import numpy as np
from lightfm import LightFM
from lightfm.data import Dataset
from scipy.sparse import csr_matrix
from ..models import User, Movie, Rating
from django.conf import settings
import os
import pickle
import logging
from django.db.models import Count, Q
import psutil
import json
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

# --- Конфігурація та кешування ---
MODEL_DIR = os.path.join(settings.BASE_DIR, 'ml_models')
MODEL_PATH = os.path.join(MODEL_DIR, 'lightfm_model.pkl')
DATA_PATH = os.path.join(MODEL_DIR, 'lightfm_data.pkl')
os.makedirs(MODEL_DIR, exist_ok=True)

# --- Параметри LightFM ---
LIGHTFM_NO_COMPONENTS = 5
LIGHTFM_LEARNING_RATE = 0.01
LIGHTFM_ITEM_ALPHA = 1e-6
LIGHTFM_USER_ALPHA = 1e-6
LIGHTFM_EPOCHS = 50
LIGHTFM_NUM_THREADS = 4
LIGHTFM_LOSS_FUNCTION = 'warp'


def _log_memory_usage():
    """Логує використання пам'яті."""
    try:
        mem = psutil.virtual_memory()
        logger.info(
            f"Використання пам'яті: {mem.percent}% (всього: {mem.total // (1024 ** 2)}МБ, використано: {mem.used // (1024 ** 2)}МБ)"
        )
    except Exception as e:
        logger.warning(f"Не вдалося залогувати використання пам'яті: {e}")


def _clear_cache():
    """Очищає кеш моделі та даних з диска."""
    for path in [MODEL_PATH, DATA_PATH]:
        if os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"Видалено кешований файл: {path}")
            except Exception as e:
                logger.error(f"Помилка при видаленні {path}: {e}", exc_info=True)
    logger.info("Дисковий кеш очищено.")


def _safe_json_parse(json_data):
    """Безпечно парсить JSON дані. Повертає список."""
    if isinstance(json_data, list):
        return json_data
    if isinstance(json_data, str) and json_data:
        try:
            parsed = json.loads(json_data)
            # Якщо JSON розпарсився в не-список (наприклад, одиночний об'єкт або рядок), обертаємо його в список
            return parsed if isinstance(parsed, list) else [parsed]
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Помилка розбору JSON: {e}. Повертаю порожній список для даних: '{json_data}'")
            return []
    return []


def _prepare_lightfm_data_for_training():
    logger.info("Початок підготовки даних для навчання LightFM з бази даних...")
    _log_memory_usage()


    default_return = (None,) * 10

    try:
        users_for_training_queryset = User.objects.annotate(
            num_ratings=Count('ratings')
        ).filter(num_ratings__gte=settings.MIN_USER_RATINGS_FOR_TRAINING, is_active=True)
        eligible_user_ids_str = [str(u_id) for u_id in
                                 users_for_training_queryset.values_list('id', flat=True).order_by('id')]

        if not eligible_user_ids_str:
            logger.warning(
                f"Не знайдено користувачів принаймні з {settings.MIN_USER_RATINGS_FOR_TRAINING} оцінками або активних користувачів. Скасування підготовки даних."
            )
            return default_return

        logger.info(f"Виявлено {len(eligible_user_ids_str)} підходящих користувачів для навчання.")

        all_db_movie_ids_str = [str(m_id) for m_id in Movie.objects.values_list('id', flat=True).order_by('id')]
        all_db_user_ids_str = [str(u_id) for u_id in User.objects.values_list('id', flat=True).order_by('id')]

        ratings_for_training = Rating.objects.filter(
            user_id__in=[int(uid) for uid in eligible_user_ids_str]
        ).select_related('movie', 'user')

        if not ratings_for_training.exists():
            logger.warning("Не знайдено оцінок для підходящих користувачів. Скасування підготовки даних.")
            return default_return

        logger.info(f"Отримано {ratings_for_training.count()} оцінок для навчання.")

        actual_user_ids_from_ratings = set()
        actual_movie_ids_from_ratings = set()
        interactions_input_for_build = []

        for rating in ratings_for_training:
            user_str_id = str(rating.user.id)
            movie_str_id = str(rating.movie.id)
            normalized_score = max(0.0, min(1.0, rating.score / 10.0))

            actual_user_ids_from_ratings.add(user_str_id)
            actual_movie_ids_from_ratings.add(movie_str_id)
            interactions_input_for_build.append((user_str_id, movie_str_id, normalized_score))

        all_active_user_ids = sorted(list(actual_user_ids_from_ratings))
        all_movie_ids_in_db = sorted(list(set(all_db_movie_ids_str)))

        logger.info(
            f"Всього активних користувачів (з оцінками): {len(all_active_user_ids)}, Всього фільмів у БД: {len(all_movie_ids_in_db)}")
        logger.debug(f"Приклад all_active_user_ids: {all_active_user_ids[:min(10, len(all_active_user_ids))]}")
        logger.debug(f"Приклад all_movie_ids_in_db: {all_movie_ids_in_db[:min(10, len(all_movie_ids_in_db))]}")

        movies_for_feature_extraction_queryset = Movie.objects.filter(
            id__in=[int(mid) for mid in all_movie_ids_in_db]
        ).order_by('id')

        movie_obj_map = {str(m.id): m for m in movies_for_feature_extraction_queryset}
        movies_for_feature_extraction_ids = list(movie_obj_map.keys())

        logger.info(f"Виявлено {len(movies_for_feature_extraction_ids)} фільмів для вилучення ознак.")

        all_item_feature_names_set = set()
        features_by_movie_id = {}

        def add_processed_json_features(json_data, prefix, feature_list_collector, limit=None):
            parsed_data = _safe_json_parse(json_data)
            temp_features = []
            for item in parsed_data:
                if isinstance(item, dict) and 'name' in item and item['name']:
                    val = str(item['name']).strip().lower().replace(' ', '_')
                elif isinstance(item, str) and item:
                    val = item.strip().lower().replace(' ', '_')
                else:
                    continue

                if val:
                    temp_features.append(f"{prefix}:{val}")

            if limit and len(temp_features) > limit:
                temp_features = temp_features[:limit]

            feature_list_collector.extend(temp_features)
            for feature in temp_features:
                all_item_feature_names_set.add(feature)

        for movie_id_str in all_movie_ids_in_db:
            movie_obj = movie_obj_map.get(movie_id_str)
            if not movie_obj:
                logger.error(
                    f"КРИТИЧНА ПОМИЛКА: Фільм з ID {movie_id_str} не знайдено в movie_obj_map, хоча очікувався.")
                continue

            current_movie_features = []

            add_processed_json_features(movie_obj.genres_json, "genre", current_movie_features)
            add_processed_json_features(movie_obj.directors_json, "director", current_movie_features)
            add_processed_json_features(movie_obj.cast_json, "actor", current_movie_features, limit=3)
            add_processed_json_features(movie_obj.keywords_json, "keyword", current_movie_features, limit=10)

            if movie_obj.release_date:
                release_year = movie_obj.release_date.year
                decade = (release_year // 10) * 10
                feature = f"decade:{decade}s"
                current_movie_features.append(feature)
                all_item_feature_names_set.add(feature)

            if hasattr(movie_obj, 'vote_average') and movie_obj.vote_average is not None and movie_obj.vote_average > 0:
                rating_bin = int(movie_obj.vote_average // 2) * 2
                feature = f"rating_bin:{rating_bin}-{rating_bin + 2}"
                current_movie_features.append(feature)
                all_item_feature_names_set.add(feature)

            unique_movie_feature = f"movie_id_:{movie_id_str}"
            if unique_movie_feature not in current_movie_features:
                current_movie_features.append(unique_movie_feature)
            all_item_feature_names_set.add(unique_movie_feature)

            features_by_movie_id[movie_id_str] = current_movie_features

        item_features_raw_for_build = []
        for movie_id_str in all_movie_ids_in_db:
            features = features_by_movie_id.get(movie_id_str)
            if features is not None:
                item_features_raw_for_build.append((movie_id_str, features))
            else:
                logger.warning(
                    f"Фільм {movie_id_str} не мав згенерованих ознак, його пропущено в item_features_raw_for_build.")

        all_unique_feature_names_list = sorted(list(all_item_feature_names_set))
        logger.info(
            f"Зібрано {len(all_unique_feature_names_list)} унікальних назв ознак елементів (включно з ознаками movie_id).")

        logger.info(f"ДЕБАГ: item_features_raw_for_build містить {len(item_features_raw_for_build)} записів.")
        found_movies_in_features_build = {item_id for item_id, _ in item_features_raw_for_build}
        missing_from_features_build = set(all_movie_ids_in_db) - found_movies_in_features_build
        if missing_from_features_build:
            logger.error(
                f"ДЕБАГ: !!! КРИТИЧНО !!! Фільми з all_movie_ids_in_db відсутні в item_features_raw_for_build (це означає, що вони не матимуть ознак): {missing_from_features_build}")
        else:
            logger.info("ДЕБАГ: Усі фільми з all_movie_ids_in_db присутні в item_features_raw_for_build.")

        logger.info("ДЕБАГ: Приклад item_features_raw_for_build (перші 5 та останні 5 записів):")
        for i, (movie_id, features) in enumerate(item_features_raw_for_build):
            if i < 5 or i >= len(item_features_raw_for_build) - 5:
                logger.info(
                    f"  ID фільму: {movie_id}, Кількість ознак: {len(features)}, Приклад ознак: {features[:3]}...")
            if i == 5 and len(item_features_raw_for_build) > 10:
                logger.info("  ...")

        dataset = Dataset()

        dataset.fit(
            users=all_db_user_ids_str,
            items=all_movie_ids_in_db,
            user_features=[],
            item_features=all_unique_feature_names_list
        )


        user_id_map, user_feature_map, item_id_map, item_feature_map = dataset.mapping()

        logger.info(
            f"LightFM Dataset ініціалізовано. Зіставлені користувачі: {len(user_id_map)}, Зіставлені фільми: {len(item_id_map)}"
        )

        expected_mapped_movies_count = len(all_movie_ids_in_db)
        actual_mapped_movies_count = len(item_id_map)

        if actual_mapped_movies_count != expected_mapped_movies_count:
            missing_movie_ids = set(all_movie_ids_in_db) - set(item_id_map.keys())
            logger.error(
                f"КРИТИЧНА НЕСУМІСНІСТЬ ЗІСТАВЛЕННЯ: Очікувалося {expected_mapped_movies_count} зіставлених фільмів, але отримано {actual_mapped_movies_count}. "
                f"Відсутні ID фільмів: {missing_movie_ids}"
            )
            return default_return
        else:
            logger.info("Зіставлення набору даних узгоджене. Всі очікувані фільми зіставлені.")

        if not interactions_input_for_build:
            logger.error(
                "Немає дійсних даних взаємодії після фільтрації та зіставлення. Неможливо побудувати матрицю взаємодій.")
            return default_return

        logger.info(f"Підготовлено {len(interactions_input_for_build)} взаємодій для побудови матриці.")

        interactions_matrix, _ = dataset.build_interactions(interactions_input_for_build)
        logger.info(
            f"Побудовано матрицю взаємодій: {interactions_matrix.shape}, {interactions_matrix.nnz} ненульових записів."
        )

        if interactions_matrix.nnz == 0:
            logger.error("Матриця взаємодій порожня (немає ненульових записів). Скасування підготовки даних.")
            return default_return

        item_features_matrix = None
        if item_features_raw_for_build:
            logger.info(f"Будуємо ознаки елементів для {len(item_features_raw_for_build)} фільмів.")
            item_features_matrix = dataset.build_item_features(item_features_raw_for_build)
            logger.info(
                f"Побудовано матрицю ознак елементів: {item_features_matrix.shape}, {item_features_matrix.nnz} ненульових записів."
            )
            if item_features_matrix.nnz == 0:
                logger.warning(
                    "Матриця ознак елементів має нуль ненульових записів. Ознаки можуть бути оброблені неправильно.")
        else:
            logger.warning(
                "Не знайдено дійсних ознак елементів для build_item_features. Матриця ознак елементів буде None.")

        user_features_matrix = dataset.build_user_features([])
        logger.info(f"Розмір матриці ознак користувачів: {user_features_matrix.shape}")

        _log_memory_usage()
        logger.info("Підготовка даних успішно завершена.")


        return (
            dataset,
            interactions_matrix,
            item_features_matrix,
            user_features_matrix,
            user_id_map,
            item_id_map,
            all_unique_feature_names_list,  # item_feature_names
            [],

            item_feature_map,
            user_feature_map
        )

    except Exception as e:
        logger.exception(f"Під час підготовки даних LightFM сталася помилка: {e}")
        return default_return


def get_lightfm_model_and_data_from_cache():
    if os.path.exists(MODEL_PATH) and os.path.exists(DATA_PATH):
        try:
            with open(MODEL_PATH, 'rb') as f:
                model = pickle.load(f)
            with open(DATA_PATH, 'rb') as f:
                data = pickle.load(f)

            reconstructed_dataset = Dataset()

            cached_user_ids = list(data['user_id_map'].keys())
            cached_item_ids = list(data['item_id_map'].keys())
            cached_item_feature_names = data.get('item_feature_names', [])
            # ЗМІНА 5: Витягуємо cached_user_feature_names зі збережених даних
            cached_user_feature_names = data.get('user_feature_names', [])

            # ЗМІНА 6: Dataset.fit() тепер приймає user_features
            reconstructed_dataset.fit(
                users=cached_user_ids,
                items=cached_item_ids,
                user_features=cached_user_feature_names,  # Додано
                item_features=cached_item_feature_names
            )

            cached_item_feature_map = data.get('item_feature_map')
            if not cached_item_feature_map:
                _, _, _, cached_item_feature_map = reconstructed_dataset.mapping()
                logger.warning("item_feature_map не знайдено в кеші, відтворено з Dataset.mapping().")

            # ЗМІНА 7: Витягуємо cached_user_feature_map
            cached_user_feature_map = data.get('user_feature_map')
            if not cached_user_feature_map:
                # Відновлюємо user_feature_map, якщо його немає в кеші
                _, cached_user_feature_map, _, _ = reconstructed_dataset.mapping()
                logger.warning("user_feature_map не знайдено в кеші, відтворено з Dataset.mapping().")

            logger.info("Модель та дані LightFM завантажено з дискового кешу.")
            # ЗМІНА 8: Повертаємо 10 значень
            return (
                model,
                reconstructed_dataset,
                data['interactions_matrix'],
                data.get('item_features_matrix'),
                data.get('user_features_matrix'),
                data['user_id_map'],
                data['item_id_map'],
                cached_item_feature_names,
                cached_user_feature_names,  # user_feature_names
                cached_item_feature_map,  # item_feature_map
                # ЗМІНА 9: Додаємо user_feature_map як 10-й елемент
                cached_user_feature_map
            )
        except Exception as e:
            logger.error(f"Помилка при завантаженні моделі LightFM або даних з кешу: {e}. Кеш буде очищено.",
                         exc_info=True)
            _clear_cache()
    else:
        logger.warning(
            f"Файли моделі LightFM не знайдено за шляхами {MODEL_PATH} або {DATA_PATH}. Буде здійснено спробу навчання.")

    # ЗМІНА 10: Повертаємо 10 None-ів, якщо завантаження не вдалося
    return (None,) * 10


def train_lightfm_model(force_retrain=False):
    if force_retrain:
        logger.info("force_retrain увімкнено. Очищення дискового кешу та початок навчання.")
        _clear_cache()
    else:
        logger.info("Спроба завантажити модель LightFM з кешу без force_retrain.")

    model_data = get_lightfm_model_and_data_from_cache()

    if model_data[0] is not None:
        logger.info("Модель та дані LightFM успішно завантажено з кешу.")
        return model_data

    logger.info("Модель LightFM не знайдена або потребує перенавчання. Початок процесу навчання.")


    dataset, interactions_matrix, item_features_matrix, user_features_matrix, \
        user_id_map, item_id_map, item_feature_names, user_feature_names, \
        item_feature_map, user_feature_map = \
        _prepare_lightfm_data_for_training()

    # ЗМІНА 12: Перевіряємо всі 10 елементів
    if dataset is None or interactions_matrix is None or item_features_matrix is None or \
            user_id_map is None or item_id_map is None or \
            item_feature_names is None or user_feature_names is None or \
            item_feature_map is None or user_feature_map is None:  # Додано перевірки
        logger.error("Не вдалося підготувати дані для навчання моделі LightFM. Скасування навчання.")
        return (None,) * 10  # ЗМІНА 13: Повертаємо 10 None-ів

    model = LightFM(
        no_components=LIGHTFM_NO_COMPONENTS,
        learning_rate=LIGHTFM_LEARNING_RATE,
        item_alpha=LIGHTFM_ITEM_ALPHA,
        user_alpha=LIGHTFM_USER_ALPHA,
        loss=LIGHTFM_LOSS_FUNCTION
    )

    logger.info("Початок навчання моделі LightFM...")
    try:
        model.fit(
            interactions_matrix,
            item_features=item_features_matrix,
            user_features=user_features_matrix,
            epochs=LIGHTFM_EPOCHS,
            num_threads=LIGHTFM_NUM_THREADS,
            verbose=True
        )
        logger.info("Навчання моделі LightFM завершено УСПІШНО.")  # <--- ДОДАЙТЕ ЦЕЙ РЯДОК
    except Exception as e:
        logger.error(f"Помилка під час навчання моделі LightFM: {e}", exc_info=True)
        return (None,) * 10

    data_to_save = {
        'user_id_map': user_id_map,
        'item_id_map': item_id_map,
        'item_feature_names': item_feature_names,
        'user_feature_names': user_feature_names,  # ЗМІНА 15: Зберігаємо user_feature_names
        'item_feature_map': item_feature_map,
        'user_feature_map': user_feature_map,  # ЗМІНА 16: Зберігаємо user_feature_map
        'interactions_matrix': interactions_matrix,
        'item_features_matrix': item_features_matrix,
        'user_features_matrix': user_features_matrix,
    }

    try:
        with open(MODEL_PATH, 'wb') as f:
            pickle.dump(model, f)
        with open(DATA_PATH, 'wb') as f:
            pickle.dump(data_to_save, f)
        logger.info(f"Модель збережено в: {MODEL_PATH}")
        logger.info(f"Дані збережено в: {DATA_PATH}")
    except Exception as e:
        logger.error(f"Помилка при збереженні моделі або даних: {e}", exc_info=True)
        _clear_cache()
        return (None,) * 10  # ЗМІНА 17: Повертаємо 10 None-ів

    # ЗМІНА 18: Повертаємо 10 значень
    return (
        model,
        dataset,
        interactions_matrix,
        item_features_matrix,
        user_features_matrix,
        user_id_map,
        item_id_map,
        item_feature_names,
        user_feature_names,  # user_feature_names
        item_feature_map,
        user_feature_map  # user_feature_map
    )


def get_popular_movies(num_recommendations=10):
    logger.info(f"Отримання {num_recommendations} популярних фільмів як запасний варіант.")
    try:
        popular_movies = Movie.objects.annotate(
            num_ratings=Count('ratings')
        ).filter(
            num_ratings__gte=settings.MIN_USER_RATINGS_FOR_RECOMMENDATION
        ).order_by('-num_ratings', '-vote_average').distinct()[:num_recommendations]

        return list(popular_movies)
    except Exception as e:
        logger.error(f"Помилка при отриманні популярних фільмів: {e}", exc_info=True)
        return []