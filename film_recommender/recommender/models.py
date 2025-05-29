from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator


class User(AbstractUser):
    """
    Стандартна модель користувача Django, розширена з AbstractUser.
    Залишається без змін, як було запропоновано.
    """
    pass


class Movie(models.Model):
    """
    Модель фільму, розширена додатковими характеристиками
    для покращення контентної фільтрації LightFM.
    """
    tmdb_id = models.IntegerField(unique=True)
    title = models.CharField(max_length=255)
    overview = models.TextField(blank=True, null=True)
    release_date = models.DateField(blank=True, null=True)
    poster_path = models.CharField(max_length=255, blank=True, null=True)
    poster_url = models.URLField(max_length=500, blank=True, null=True)
    backdrop_path = models.CharField(max_length=255, blank=True, null=True)
    backdrop_url = models.URLField(max_length=500, blank=True, null=True)
    vote_average = models.FloatField(default=0.0)
    vote_count = models.IntegerField(default=0)
    genres_json = models.JSONField(default=list, blank=True, null=True)

    # --- Нові поля для додаткових характеристик фільмів ---
    # Поле для зберігання режисерів як JSON-списку або простого CharField
    # Якщо ви отримуєте кілька режисерів, JSONField кращий.
    # Приклад структури в JSONField: [{"id": 123, "name": "Christopher Nolan"}]
    directors_json = models.JSONField(default=list, blank=True, null=True)

    # Поле для зберігання акторів як JSON-списку
    # Приклад структури: [{"id": 456, "name": "Leonardo DiCaprio", "character": "Cobb"}]
    cast_json = models.JSONField(default=list, blank=True, null=True)

    # Поле для зберігання країн виробництва як JSON-списку
    # Приклад структури: [{"iso_3166_1": "US", "name": "United States of America"}]
    production_countries_json = models.JSONField(default=list, blank=True, null=True)

    # Поле для зберігання мов як JSON-списку
    # Приклад структури: [{"iso_639_1": "en", "name": "English"}]
    spoken_languages_json = models.JSONField(default=list, blank=True, null=True)

    # Поле для зберігання тегів або ключових слів як JSON-списку
    # Приклад структури: [{"id": 789, "name": "sci-fi"}]
    keywords_json = models.JSONField(default=list, blank=True, null=True)

    # --- Кінець нових полів ---

    def __str__(self):
        return self.title

    @property
    def genres_display(self):
        """Повертає жанри як рядок, розділений комами."""
        if isinstance(self.genres_json, list):
            return ", ".join(
                g['name'] for g in self.genres_json
                if isinstance(g, dict) and 'name' in g
            )
        return ""

    @property
    def directors_display(self):
        """Повертає режисерів як рядок, розділений комами."""
        if isinstance(self.directors_json, list):
            return ", ".join(
                d['name'] for d in self.directors_json
                if isinstance(d, dict) and 'name' in d
            )
        return ""

    @property
    def cast_display(self):
        """Повертає основних акторів як рядок, розділений комами (можна обмежити кількість)."""
        if isinstance(self.cast_json, list):
            # Можна обмежити до кількох основних акторів
            return ", ".join(
                a['name'] for a in self.cast_json[:3] # Обмеження до 3 акторів
                if isinstance(a, dict) and 'name' in a
            )
        return ""

    @property
    def production_countries_display(self):
        """Повертає країни виробництва як рядок, розділений комами."""
        if isinstance(self.production_countries_json, list):
            return ", ".join(
                c['name'] for c in self.production_countries_json
                if isinstance(c, dict) and 'name' in c
            )
        return ""

    @property
    def spoken_languages_display(self):
        """Повертає мови як рядок, розділений комами."""
        if isinstance(self.spoken_languages_json, list):
            return ", ".join(
                l['name'] for l in self.spoken_languages_json
                if isinstance(l, dict) and 'name' in l
            )
        return ""

    @property
    def keywords_display(self):
        """Повертає ключові слова/теги як рядок, розділений комами."""
        if isinstance(self.keywords_json, list):
            return ", ".join(
                k['name'] for k in self.keywords_json
                if isinstance(k, dict) and 'name' in k
            )
        return ""

    class Meta:
        verbose_name = "Movie"
        verbose_name_plural = "Movies"
        ordering = ['title']


class Rating(models.Model):
    """
    Модель для зберігання оцінок фільмів користувачами.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ratings', db_index=True)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='ratings', db_index=True)
    score = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(10)])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} rated {self.movie.title} with {self.score}"

    class Meta:
        unique_together = ('user', 'movie') # Користувач може оцінити фільм лише один раз
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['movie']),
            models.Index(fields=['score']),
        ]
        verbose_name = "Rating"
        verbose_name_plural = "Ratings"
        ordering = ['-created_at']


class UserRecommendation(models.Model):
    """
    Модель для зберігання згенерованих рекомендацій для користувачів.
    Дозволяє кешувати рекомендації та уникати повторних обчислень.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_recommendations', db_index=True)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, db_index=True)
    score = models.FloatField() # Прогнозована оцінка або релевантність
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Recommended {self.movie.title} to {self.user.username} (score: {self.score:.2f})"

    class Meta:
        unique_together = ('user', 'movie') # Користувач отримує одну рекомендацію для конкретного фільму
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['movie']),
            models.Index(fields=['score']),
        ]
        verbose_name = "User Recommendation"
        verbose_name_plural = "User Recommendations"
        ordering = ['-score'] # Сортуємо за оцінкою, щоб бачити найрелевантніші першими