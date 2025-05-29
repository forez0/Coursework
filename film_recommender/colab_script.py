import os
import django
from django.conf import settings
import pickle
import pandas as pd
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'film_recommender.settings')

django.setup()

# Import the function that prepares LightFM data
from recommender.ml.lightfm_model import _prepare_lightfm_data_for_training

if __name__ == '__main__':
    logger.info("Запуск скрипта експорту даних для Google Colab...")

    # *** THIS IS THE CRUCIAL CHANGE ***
    # Ensure you are unpacking ALL 9 values that _prepare_lightfm_data_for_training returns
    dataset, interactions_matrix, item_features_matrix, user_features_matrix, \
        user_id_map, item_id_map, item_feature_names, user_feature_names, \
        item_feature_map, user_feature_map = _prepare_lightfm_data_for_training()
    # Now there are 9 variables on the left, matching the 9 items returned by the function.


    if dataset is None or interactions_matrix is None or item_features_matrix is None:
        logger.error(
            "Не вдалося підготувати дані для експорту. Перевірте логи функції _prepare_lightfm_data_for_training.")
        sys.exit(1)
    else:
        try:
            export_dir = os.path.join(settings.BASE_DIR, 'exported_data_for_colab')
            os.makedirs(export_dir, exist_ok=True)

            logger.info("Побудова DataFrame для взаємодій...")
            inv_user_id_map = {v: k for k, v in user_id_map.items()}
            inv_item_id_map = {v: k for k, v in item_id_map.items()}

            interactions_df_rows = []
            for user_internal_id, item_internal_id, score in zip(
                    interactions_matrix.row, interactions_matrix.col, interactions_matrix.data
            ):
                user_original_id = inv_user_id_map.get(user_internal_id)
                movie_original_id = inv_item_id_map.get(item_internal_id)
                if user_original_id and movie_original_id:
                    interactions_df_rows.append({
                        'user_id': int(user_original_id),
                        'movie_id': int(movie_original_id),
                        'score': float(score * 10)
                    })
            interactions_df = pd.DataFrame(interactions_df_rows)
            logger.info(f"Побудовано DataFrame взаємодій: {interactions_df.shape[0]} рядків.")

            logger.info("Побудова DataFrame для ознак елементів...")
            # item_feature_map is now directly available from unpacking, no need for dataset.mapping()
            if item_feature_map is None:
                logger.error("item_feature_map виявився None після розпакування. Перевірте _prepare_lightfm_data_for_training.")
                sys.exit(1)

            feature_names_ordered = [name for name, _ in sorted(item_feature_map.items(), key=lambda x: x[1])]
            item_features_df_rows = []
            num_items, num_features = item_features_matrix.shape

            for item_internal_id in range(num_items):
                original_movie_id = inv_item_id_map.get(item_internal_id)
                if original_movie_id is None:
                    continue

                row = {'movie_id': int(original_movie_id)}
                for feature_internal_id in item_features_matrix[item_internal_id].indices:
                    if feature_internal_id < len(feature_names_ordered):
                        feature_name = feature_names_ordered[feature_internal_id]
                        row[feature_name] = 1
                    else:
                        logger.warning(f"Feature ID {feature_internal_id} out of bounds for movie {original_movie_id}.")

                for feature_name in feature_names_ordered:
                    if feature_name not in row:
                        row[feature_name] = 0

                item_features_df_rows.append(row)

            item_features_df = pd.DataFrame(item_features_df_rows)
            cols = ['movie_id'] + [col for col in item_features_df.columns if col != 'movie_id']
            item_features_df = item_features_df[cols]

            logger.info(
                f"Побудовано DataFrame ознак елементів: {item_features_df.shape[0]} рядків, {item_features_df.shape[1]} колонок.")

            interactions_df.to_csv(os.path.join(export_dir, 'interactions.csv'), index=False)
            item_features_df.to_csv(os.path.join(export_dir, 'item_features.csv'), index=False)
            logger.info("Дані збережено у форматі CSV.")

            with open(os.path.join(export_dir, 'interactions.pkl'), 'wb') as f:
                pickle.dump(interactions_df, f)
            with open(os.path.join(export_dir, 'item_features.pkl'), 'wb') as f:
                pickle.dump(item_features_df, f)
            logger.info("Дані збережено у форматі PKL.")

            mappings_to_save = {
                'user_id_map': user_id_map,
                'item_id_map': item_id_map,
                'item_feature_names': item_feature_names,
                'user_feature_names': user_feature_names,
                'item_feature_map': item_feature_map,
            }
            with open(os.path.join(export_dir, 'lightfm_mappings.pkl'), 'wb') as f:
                pickle.dump(mappings_to_save, f)
            logger.info("Мапінги LightFM збережено до lightfm_mappings.pkl.")

            logger.info(f"Дані успішно експортовано до {export_dir}")

        except Exception as e:
            logger.exception("Помилка під час експорту або збереження даних.")