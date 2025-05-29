from django.core.management.base import BaseCommand, CommandError
import random
from django.contrib.auth import get_user_model
from ...models import Movie, Rating # Assuming your models are in 'recommender_app'
from django.db import transaction

User = get_user_model()

NUM_TEST_USERS = 150
RATINGS_PER_USER = 70
MIN_SCORE = 1
MAX_SCORE = 10


class Command(BaseCommand):
    help = 'Generates test users and movie ratings for the recommender system.'

    def handle(self, *args, **options):
        self.stdout.write("--- Початок генерації тестових даних ---")

        # The _generate_test_data function is good to keep for encapsulation,
        # but it doesn't need to be defined inside handle every time.
        # However, for a simple script like this, it's fine.

        @transaction.atomic
        def _generate_test_data():
            # 1. Очистка старих тестових даних
            test_users = User.objects.filter(username__startswith='testuser')
            Rating.objects.filter(user__in=test_users).delete()
            deleted_count, _ = test_users.delete()
            self.stdout.write(f"Видалено {deleted_count} тестових користувачів та їх оцінки.")

            # 2. Перевірка наявності фільмів
            all_movies = list(Movie.objects.all())
            if not all_movies:
                raise CommandError("Помилка: Немає фільмів у базі даних. Спочатку імпортуйте фільми!")

            # 3. Налаштування кількості оцінок
            # Ensure ratings_per_user doesn't exceed the number of available movies
            actual_ratings_per_user = min(RATINGS_PER_USER, len(all_movies))
            if actual_ratings_per_user < RATINGS_PER_USER:
                self.stdout.write(self.style.WARNING(
                    f"Увага: Фільмів ({len(all_movies)}) менше, ніж бажана кількість оцінок на користувача ({RATINGS_PER_USER}). "
                    f"Кожен користувач оцінить до {actual_ratings_per_user} фільмів."
                ))
            else:
                self.stdout.write(f"Кожен користувач оцінить {actual_ratings_per_user} фільмів.")


            # 4. Генерація користувачів
            users_created = []
            ratings_created = 0
            # Keep track of movie IDs that have been rated by at least one user
            global_rated_movie_ids = set()

            for i in range(1, NUM_TEST_USERS + 1):
                username = f'testuser{i}'
                user = User.objects.create_user(
                    username=username,
                    email=f'test{i}@example.com',
                    password='password123'
                )
                users_created.append(user)
                self.stdout.write(f"Створено користувача: {username}")

                movies_to_rate = []

                if i == 1:
                    # The first user rates a subset of movies equal to actual_ratings_per_user
                    # or all movies if actual_ratings_per_user is greater than total movies.
                    movies_to_rate = random.sample(all_movies, actual_ratings_per_user)
                else:
                    # For subsequent users, select a mix of already rated and unrated movies
                    # to ensure better coverage and realistic data.

                    # Prioritize unrated movies if available
                    unrated_movies = [m for m in all_movies if m.id not in global_rated_movie_ids]
                    num_unrated_to_add = min(random.randint(1, actual_ratings_per_user), len(unrated_movies))
                    if unrated_movies and num_unrated_to_add > 0:
                        movies_to_rate.extend(random.sample(unrated_movies, num_unrated_to_add))

                    # Fill the rest with randomly chosen movies from the entire set
                    # ensuring no duplicates for the current user's rating list
                    remaining_slots = actual_ratings_per_user - len(movies_to_rate)
                    if remaining_slots > 0:
                        already_selected_for_user = {m.id for m in movies_to_rate}
                        available_for_random = [m for m in all_movies if m.id not in already_selected_for_user]
                        movies_to_rate.extend(random.sample(
                            available_for_random,
                            min(remaining_slots, len(available_for_random))
                        ))

                # Create ratings for the selected movies
                for movie in movies_to_rate:
                    score = random.randint(MIN_SCORE, MAX_SCORE)
                    Rating.objects.create(user=user, movie=movie, score=score)
                    ratings_created += 1
                    global_rated_movie_ids.add(movie.id) # Update global set
                    self.stdout.write(f"  Додано оцінку: {movie.title} - {score}/10")

            # 5. Перевірка результатів
            self.stdout.write(self.style.SUCCESS("\n--- Результати генерації ---"))
            self.stdout.write(f"Створено користувачів: {len(users_created)}")
            self.stdout.write(f"Створено оцінок: {ratings_created}")

            # Статистика покриття фільмів
            rated_count = len(global_rated_movie_ids)
            coverage = rated_count / len(all_movies) * 100
            self.stdout.write(f"\nФільмів з оцінками: {rated_count} з {len(all_movies)} ({coverage:.1f}%)")

            if rated_count < len(all_movies):
                unrated = len(all_movies) - rated_count
                self.stdout.write(self.style.WARNING(
                    f"Увага: {unrated} фільмів не мають жодної оцінки!"
                ))
            else:
                self.stdout.write(self.style.SUCCESS("Усі фільми мають принаймні одну оцінку."))


        _generate_test_data()