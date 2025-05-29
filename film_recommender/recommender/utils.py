import requests
import json
import logging
from django.conf import settings
from django.core.cache import cache
from .models import Movie  # Припускаємо, що це recommender.models

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
GENRE_MAP_CACHE_KEY = 'tmdb_genre_map'


def get_tmdb_api_key():
    """Повертає ключ API TMDb з налаштувань Django."""
    api_key = settings.TMDB_API_KEY
    if not api_key:
        logger.critical("TMDB_API_KEY не встановлено в налаштуваннях. Це критична помилка.")
        raise ValueError("TMDB_API_KEY is not configured in Django settings.")
    return api_key


def get_movie_poster_url(path, size='w500'):
    """
    Повертає повний URL для постеру або фонового зображення фільму.
    Параметр `path` - це `poster_path` або `backdrop_path` з TMDb.
    Параметр `size` може бути 'w92', 'w154', 'w185', 'w342', 'w500', 'w780', 'original'.
    """
    if path:
        return f"https://image.tmdb.org/t/p/{size}{path}"
    return None


def fetch_from_tmdb(endpoint, params=None, cache_timeout=3600):
    """
    Виконує запит до TMDb API, використовуючи кешування.
    """
    try:
        api_key = get_tmdb_api_key()
    except ValueError as e:
        logger.critical(f"Fatal error: {e}")
        return None

    url = f"{TMDB_BASE_URL}/{endpoint}"
    params = params or {}
    params['api_key'] = api_key

    if 'language' not in params:
        params['language'] = getattr(settings, 'TMDB_DEFAULT_LANGUAGE', 'uk-UA')

    cache_key = f"tmdb_api_cache:{endpoint}:{json.dumps(params, sort_keys=True)}"
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.debug(f"Cache hit for {endpoint} with params {params}")
        return cached_data

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data, cache_timeout)
        logger.debug(f"Fetched and cached {endpoint} with params {params}")
        return data
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 'N/A'
        response_text = e.response.text[:200] if e.response is not None else 'N/A'
        logger.error(f"HTTP Error fetching from TMDb ({endpoint}): {status_code} - {response_text}")
        return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection Error to TMDb ({endpoint}): {e}")
        return None
    except requests.exceptions.Timeout as e:
        logger.error(f"Request Timeout to TMDb ({endpoint}): {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"General Request Error to TMDb ({endpoint}): {e}")
        return None
    except json.JSONDecodeError as e:
        response_text = response.text[:200] if 'response' in locals() and response.text else 'N/A'
        logger.error(f"JSON Decode Error from TMDb response ({endpoint}): {e} - Response: {response_text}...")
        return None


def get_tmdb_genres():
    """Отримує та кешує список жанрів TMDb."""
    genre_map = cache.get(GENRE_MAP_CACHE_KEY)
    if genre_map:
        return genre_map

    data = fetch_from_tmdb("genre/movie/list", cache_timeout=604800)  # Кешуємо на 7 днів
    if data and 'genres' in data:
        genre_map = {genre['id']: genre['name'] for genre in data['genres']}
        cache.set(GENRE_MAP_CACHE_KEY, genre_map, 604800)
        return genre_map
    logger.error("Failed to retrieve genre list from TMDb.")
    return {}


def get_genre_names(genre_ids):
    """Перетворює список ID жанрів на їхні назви."""
    genre_map = get_tmdb_genres()
    return [genre_map.get(gid, f"Genre_ID_{gid}_Not_Found") for gid in genre_ids]


def import_movie_from_tmdb(tmdb_id):
    """
    Імпортує або оновлює фільм з TMDb до локальної бази даних,
    включаючи розширені характеристики для LightFM.
    """
    movie_details = fetch_from_tmdb(f"movie/{tmdb_id}")
    if not movie_details:
        logger.error(f"Failed to get main movie data for TMDB ID: {tmdb_id}")
        return None

    # Додатковий запит для отримання даних про акторів та режисерів
    credits_data = fetch_from_tmdb(f"movie/{tmdb_id}/credits")
    if not credits_data:
        logger.warning(f"Failed to get credits data for TMDB ID: {tmdb_id}. Some features will be missing.")

    # Перевірка наявності необхідних полів
    if not movie_details.get('id') or not movie_details.get('title'):
        logger.warning(f"Missing essential data (id or title) for TMDB ID: {tmdb_id}. Skipping import.")
        return None

    # --- Збір та нормалізація даних для нових JSONField полів ---

    # Жанри (genres_json) - вже добре обробляються
    genres_data = movie_details.get('genres', [])
    if not isinstance(genres_data, list) or \
            not all(isinstance(g, dict) and 'id' in g and 'name' in g for g in genres_data):
        logger.warning(f"Unexpected format for movie genres {tmdb_id}. Setting to empty list.")
        genres_data = []

    # Режисери (directors_json)
    directors_json = []
    if credits_data and 'crew' in credits_data:
        for crew_member in credits_data['crew']:
            if crew_member.get('job') == 'Director':
                directors_json.append({
                    'id': crew_member.get('id'),
                    'name': crew_member.get('name')
                })

    # Актори (cast_json) - обмежимо до 10 основних
    cast_json = []
    if credits_data and 'cast' in credits_data:
        for actor in credits_data['cast'][:10]:  # Обмежуємо до 10 акторів
            if actor.get('name'):
                cast_json.append({
                    'id': actor.get('id'),
                    'name': actor.get('name'),
                    'character': actor.get('character')
                })

    # Країни виробництва (production_countries_json)
    production_countries_json = movie_details.get('production_countries', [])
    if not isinstance(production_countries_json, list) or \
            not all(isinstance(c, dict) and 'iso_3166_1' in c and 'name' in c for c in production_countries_json):
        logger.warning(f"Unexpected format for production countries {tmdb_id}. Setting to empty list.")
        production_countries_json = []

    # Мови (spoken_languages_json)
    spoken_languages_json = movie_details.get('spoken_languages', [])
    if not isinstance(spoken_languages_json, list) or \
            not all(isinstance(l, dict) and 'iso_639_1' in l and 'name' in l for l in spoken_languages_json):
        logger.warning(f"Unexpected format for spoken languages {tmdb_id}. Setting to empty list.")
        spoken_languages_json = []

    # Ключові слова (keywords_json) - потребує окремого ендпоінту
    keywords_data = fetch_from_tmdb(f"movie/{tmdb_id}/keywords")
    keywords_json = []
    if keywords_data and 'keywords' in keywords_data:
        keywords_json = keywords_data['keywords']
    elif keywords_data and 'results' in keywords_data:  # Деякі API повертають 'results' для ключових слів
        keywords_json = keywords_data['results']
    if not isinstance(keywords_json, list) or \
            not all(isinstance(k, dict) and 'id' in k and 'name' in k for k in keywords_json):
        logger.warning(f"Unexpected format for keywords {tmdb_id}. Setting to empty list.")
        keywords_json = []

    poster_path = movie_details.get('poster_path')
    backdrop_path = movie_details.get('backdrop_path')

    movie_defaults = {
        'title': movie_details['title'],
        'overview': movie_details.get('overview', ''),
        'release_date': movie_details.get('release_date') or None,
        'poster_path': poster_path,
        'poster_url': get_movie_poster_url(poster_path, size='w500'),
        'backdrop_path': backdrop_path,
        'backdrop_url': get_movie_poster_url(backdrop_path, size='w1280'),
        'vote_average': movie_details.get('vote_average', 0.0),
        'vote_count': movie_details.get('vote_count', 0),
        'genres_json': genres_data,
        # --- Нові поля ---
        'directors_json': directors_json,
        'cast_json': cast_json,
        'production_countries_json': production_countries_json,
        'spoken_languages_json': spoken_languages_json,
        'keywords_json': keywords_json,
    }

    movie, created = Movie.objects.update_or_create(
        tmdb_id=movie_details['id'],
        defaults=movie_defaults
    )
    if created:
        logger.info(f"Imported new movie: {movie.title} (TMDB ID: {movie.tmdb_id})")
    else:
        logger.info(f"Updated existing movie: {movie.title} (TMDB ID: {movie.tmdb_id})")
    return movie


def get_popular_movies_tmdb(page=1):
    """
    Отримує список популярних фільмів з TMDb.
    """
    data = fetch_from_tmdb("movie/popular", params={'page': page})
    if data and 'results' in data:
        return data['results']
    return []


def search_movies_tmdb(query, page=1):
    """Пошук фільмів на TMDb."""
    if not query:
        logger.warning("Search query is empty. Returning empty results.")
        return []
    data = fetch_from_tmdb("search/movie", params={'query': query, 'page': page})
    if data and 'results' in data:
        return data['results']
    return []