from rest_framework import serializers
from .models import Movie, Rating, UserRecommendation, User
from .utils import get_genre_names  # Має повертати список назв жанрів


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email')


class MovieSerializer(serializers.ModelSerializer):
    # Існуючі поля
    genres_display = serializers.SerializerMethodField()
    directors_display = serializers.SerializerMethodField()
    cast_display = serializers.SerializerMethodField()
    production_countries_display = serializers.SerializerMethodField()
    spoken_languages_display = serializers.SerializerMethodField()
    keywords_display = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = (
            'id', 'tmdb_id', 'title', 'overview', 'release_date',
            'poster_path', 'poster_url', 'backdrop_path', 'backdrop_url',
            'vote_average', 'vote_count',
            'genres_json', 'genres_display', # Залишаємо genres_json, додаємо genres_display
            'directors_json', 'directors_display', # Додаємо directors_json і directors_display
            'cast_json', 'cast_display', # Додаємо cast_json і cast_display
            'production_countries_json', 'production_countries_display', # Додаємо production_countries_json і production_countries_display
            'spoken_languages_json', 'spoken_languages_display', # Додаємо spoken_languages_json і spoken_languages_display
            'keywords_json', 'keywords_display' # Додаємо keywords_json і keywords_display
        )

    # Методи для отримання відображуваних полів, які використовують @property з моделі Movie
    def get_genres_display(self, obj):
        # Якщо get_genre_names у вас ще потрібна, використайте її.
        # Але оскільки ви додали @property в моделі, краще використовувати її:
        return obj.genres_display
        # return get_genre_names(obj.genres_json) # Якщо ви все ще покладаєтесь на utils

    def get_directors_display(self, obj):
        return obj.directors_display

    def get_cast_display(self, obj):
        return obj.cast_display

    def get_production_countries_display(self, obj):
        return obj.production_countries_display

    def get_spoken_languages_display(self, obj):
        return obj.spoken_languages_display

    def get_keywords_display(self, obj):
        return obj.keywords_display


class RatingSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source='user.username')
    movie_title = serializers.ReadOnlyField(source='movie.title')

    class Meta:
        model = Rating
        fields = ('id', 'user', 'movie', 'movie_title', 'score', 'created_at')
        read_only_fields = ('user',)


class RecommendationSerializer(serializers.ModelSerializer):
    # MovieSerializer тепер включатиме всі нові поля фільму автоматично
    movie = MovieSerializer(read_only=True)

    class Meta:
        model = UserRecommendation
        fields = ('id', 'movie', 'score', 'created_at')
