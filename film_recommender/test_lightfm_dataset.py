from lightfm.data import Dataset
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Імітуємо ваші дані
all_users = [str(i) for i in range(1, 8)] # 7 користувачів
all_movies = [str(i) for i in range(1, 99)] # 98 фільмів

# Імітуємо ознаки (просто для прикладу, їх багато)
all_features = [f"genre:{i}" for i in range(1, 100)] + \
               [f"director:{i}" for i in range(1, 100)] + \
               [f"actor:{i}" for i in range(1, 100)] + \
               [f"keyword:{i}" for i in range(1, 100)] + \
               [f"decade:{i}s" for i in range(1900, 2020, 10)] + \
               [f"rating_bin:{i}-{i+2}" for i in range(0, 10, 2)]

logger.info(f"Test: Users count: {len(all_users)}, Movies count: {len(all_movies)}, Features count: {len(all_features)}")

dataset = Dataset()
dataset.fit(
    users=all_users,
    items=all_movies,
    item_features=all_features
)

user_id_map, item_id_map, user_feature_map, item_feature_map = dataset.mapping()

logger.info(f"Test: Mapped users: {len(user_id_map)}, Mapped movies: {len(item_id_map)}")
logger.info(f"Test: Mapped item features: {len(item_feature_map)}")

# Також можна додати перевірку на наявність конкретних ID, якщо це не 98
# print(item_id_map) # НЕ РОБІТЬ ЦЕГО ДЛЯ БАГАТЬОХ ID, лише для діагностики