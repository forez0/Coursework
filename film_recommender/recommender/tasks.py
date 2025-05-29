from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from .models import Movie, Rating, UserRecommendation
from .utils import get_popular_movies_tmdb, import_movie_from_tmdb
# Переконайтеся, що шлях до lightfm_model правильний відносно поточного файлу.
# Якщо recommender.tasks знаходиться в корені recommender, а ml в recommender/ml,
# то шлях має бути .ml.lightfm_model
from .ml.lightfm_model import train_lightfm_model, get_popular_movies # Це OK
import numpy as np
import logging

from django.conf import settings

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task
def import_popular_movies_task(num_pages=3):
    """
    Celery task for importing popular movies from TMDb.
    """
    logger.info(f"Starting import of popular movies from TMDb for {num_pages} pages...")
    imported_count = 0

    for page in range(1, num_pages + 1):
        movies_data = get_popular_movies_tmdb(page=page)
        if movies_data:
            for movie_data in movies_data:
                movie = import_movie_from_tmdb(movie_data['id'])
                if movie:
                    imported_count += 1
        else:
            logger.info(f"No more movies found on page {page}. Stopping import.")
            break

    logger.info(f"Finished importing. Total imported/updated: {imported_count}")
    return f"Imported/updated {imported_count} popular movies."


@shared_task
def generate_recommendations_task(user_id=None, force_retrain=False):
    """
    Celery task to train/load LightFM model and generate recommendations.
    If user_id is provided, generates for that user only.
    """
    task_id = generate_recommendations_task.request.id
    logger.info(f"[{task_id}] Starting recommendation task (force_retrain={force_retrain})")

    model_data = None
    try:
        # train_lightfm_model тепер повертає кортеж з усіма необхідними даними
        # або повертає None у разі помилки, логуючи її всередині.
        model_data = train_lightfm_model(force_retrain=force_retrain)

        if model_data is None:
            logger.error(f"[{task_id}] Failed to get model data from train_lightfm_model. Aborting.")
            return "Model training/loading failed: No data returned."

        # ОНОВЛЕНО: Розпаковуємо 10 значень з model_data
        model, dataset, interactions_matrix, item_features_matrix, user_features_matrix, \
            user_id_map, item_id_map, item_feature_names, user_feature_names, item_feature_map, user_feature_map_from_task = model_data

        # Додаємо більш ретельну перевірку всіх повернених об'єктів
        # user_feature_names та user_feature_map_from_task можуть бути [] або {} відповідно,
        # але не None, якщо все пройшло добре.
        if any(arg is None for arg in [model, dataset, interactions_matrix, user_id_map, item_id_map, item_feature_names, user_feature_names, item_feature_map, user_feature_map_from_task]):
            logger.error(f"[{task_id}] Incomplete or None model data returned from train_lightfm_model. Aborting.")
            return "Model training/loading failed: Incomplete data."

        logger.info(f"[{task_id}] Model and data loaded successfully.")

    except Exception as e:
        logger.exception(f"[{task_id}] Critical error during model training/loading process: {e}")
        return f"Model training/loading failed: {e}"

    # Визначаємо користувачів, для яких потрібно згенерувати рекомендації
    users_to_process = []
    if user_id:
        try:
            user_obj = User.objects.get(id=user_id, is_active=True)
            users_to_process.append(user_obj)
            logger.info(f"[{task_id}] Generating recommendations for user {user_obj.username} (ID: {user_id})")
        except User.DoesNotExist:
            logger.error(f"[{task_id}] User with ID {user_id} not found or not active.")
            return f"User {user_id} not found or not active."
    else:
        users_to_process = User.objects.annotate(num_ratings=Count('ratings')).filter(
            is_active=True
        )
        logger.info(
            f"[{task_id}] Identified {users_to_process.count()} active users to potentially generate recommendations for.")

    generated_count = 0
    total_processed_users = 0

    for user in users_to_process:
        total_processed_users += 1
        try:
            _generate_single_user_recommendations(
                user, model, dataset, interactions_matrix,
                item_features_matrix, user_features_matrix,
                user_id_map, item_id_map, task_id
            )
            generated_count += 1
        except Exception as e:
            logger.error(
                f"[{task_id}] Error generating recommendations for user {user.username} (ID: {user.id}): {e}",
                exc_info=True
            )

    message = f"Recommendations generated for {generated_count}/{total_processed_users} users."
    logger.info(f"[{task_id}] {message}")
    return message


@transaction.atomic
def _generate_single_user_recommendations(
        user, model, dataset, interactions_matrix,
        item_features_matrix, user_features_matrix,
        user_id_map, item_id_map, task_id, num_recommendations=10
):
    """
    Generate and save recommendations for one user.
    """
    logger.info(
        f"[{task_id}] Generating {num_recommendations} recommendations for user {user.username} (ID: {user.id})")

    user_str_id = str(user.id)
    user_internal_id = user_id_map.get(user_str_id)
    user_ratings_count = Rating.objects.filter(user=user).count()

    recommendations_with_scores = []

    if user_internal_id is None or user_ratings_count < settings.MIN_USER_RATINGS_FOR_RECOMMENDATION:
        reason = "not in LightFM model mapping" if user_internal_id is None else \
            f"not enough ratings ({user_ratings_count} < {settings.MIN_USER_RATINGS_FOR_RECOMMENDATION})"
        logger.warning(f"[{task_id}] User {user.id} ({user.username}) {reason}. Using fallback popular movies.")

        fallback_movies = get_popular_movies(num_recommendations)
        recommendations_with_scores = [
            {'movie': m, 'score': m.vote_average / 10.0 if m.vote_average else 0.0}
            for m in fallback_movies
        ]
    else:
        all_item_internal_ids = np.arange(interactions_matrix.shape[1])

        try:
            user_interaction_row = interactions_matrix.tocsr().getrow(user_internal_id)
            known_positives_internal_ids = user_interaction_row.indices
        except IndexError:
            logger.error(
                f"[{task_id}] User {user.id} (internal ID: {user_internal_id}) index out of bounds for interactions_matrix. This should not happen if user_internal_id is valid. Using fallback."
            )
            fallback_movies = get_popular_movies(num_recommendations)
            recommendations_with_scores = [
                {'movie': m, 'score': m.vote_average / 10.0 if m.vote_average else 0.0}
                for m in fallback_movies
            ]
        else:
            scores = model.predict(
                user_ids=user_internal_id,
                item_ids=all_item_internal_ids,
                item_features=item_features_matrix,
                user_features=user_features_matrix if user_features_matrix is not None else None,
                num_threads=settings.LIGHTFM_NUM_THREADS
            )

            scores[known_positives_internal_ids] = -np.inf

            valid_indices = np.where(scores != -np.inf)[0]

            if len(valid_indices) == 0:
                logger.warning(
                    f"[{task_id}] No unseen items with valid scores for user {user.id} ({user.username}). Using fallback popular movies.")
                fallback_movies = get_popular_movies(num_recommendations)
                recommendations_with_scores = [
                    {'movie': m, 'score': m.vote_average / 10.0 if m.vote_average else 0.0}
                    for m in fallback_movies
                ]
            else:
                actual_num_recommendations = min(num_recommendations, len(valid_indices))
                top_indices_internal = np.argsort(scores)[::-1][:actual_num_recommendations]

                inv_item_map = {v: k for k, v in item_id_map.items()}

                recommended_original_ids_set = set()
                for i_internal in top_indices_internal:
                    orig_id_str = inv_item_map.get(i_internal)
                    if orig_id_str:
                        try:
                            recommended_original_ids_set.add(int(orig_id_str))
                        except ValueError:
                            logger.warning(
                                f"[{task_id}] Invalid item ID '{orig_id_str}' in mapping for internal ID {i_internal}. Skipping.")

                movie_objects_map = {
                    m.id: m for m in Movie.objects.filter(id__in=list(recommended_original_ids_set))
                }

                for i_internal in top_indices_internal:
                    orig_id_str = inv_item_map.get(i_internal)
                    if orig_id_str:
                        orig_id = int(orig_id_str)
                        if orig_id in movie_objects_map:
                            score = float(scores[i_internal])
                            recommendations_with_scores.append({'movie': movie_objects_map[orig_id], 'score': score})
                        else:
                            logger.warning(
                                f"[{task_id}] Movie {orig_id} (internal {i_internal}) not found in DB or mapping issue for user {user.id}. Skipping."
                            )
                    else:
                        logger.warning(
                            f"[{task_id}] No original ID found for internal item ID {i_internal} in inv_item_map for user {user.id}. Skipping.")

    # Збереження рекомендацій у базу даних
    with transaction.atomic():
        deleted_count, _ = UserRecommendation.objects.filter(user=user).delete()
        logger.info(f"[{task_id}] Deleted {deleted_count} old recommendations for user {user.username} (ID: {user.id})")

        if not recommendations_with_scores:
            msg = f"[{task_id}] No valid recommendations found or generated for user {user.username} (ID: {user.id})."
            logger.info(msg)
            return msg

        recommendations_to_create = []
        for rec in recommendations_with_scores:
            score_val = rec['score']
            if np.isnan(score_val) or np.isinf(score_val):
                logger.warning(
                    f"[{task_id}] Invalid score for movie {rec['movie'].id} for user {user.id} — setting to 0.0.")
                score_val = 0.0
            score_val = max(0.0, min(1.0, score_val))
            recommendations_to_create.append(UserRecommendation(user=user, movie=rec['movie'], score=score_val))

        if recommendations_to_create:
            UserRecommendation.objects.bulk_create(recommendations_to_create)
            msg = f"[{task_id}] Saved {len(recommendations_to_create)} recommendations for user {user.username}."
            logger.info(msg)
            return msg
        else:
            msg = f"[{task_id}] No recommendations to create after filtering for user {user.username}."
            logger.info(msg)
            return msg