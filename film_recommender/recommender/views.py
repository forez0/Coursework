from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Avg
from django.contrib import messages
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from .models import Movie, Rating, UserRecommendation
from .serializers import UserSerializer, MovieSerializer, RatingSerializer, RecommendationSerializer

from .utils import import_movie_from_tmdb, search_movies_tmdb, get_movie_poster_url
from .tasks import import_popular_movies_task, generate_recommendations_task

from .forms import CustomUserCreationForm

import logging

logger = logging.getLogger(__name__)

User = get_user_model()


# --- Веб-сторінки (Django Views) ---

def index(request):
    query = request.GET.get('query')
    search_results = []

    # Виконуємо пошук тільки якщо є запит
    if query:
        tmdb_results = search_movies_tmdb(query)
        for tmdb_movie in tmdb_results:
            movie = import_movie_from_tmdb(tmdb_movie['id'])
            if movie:
                search_results.append(movie)

        if not search_results:
            messages.info(request, f"За запитом '{query}' нічого не знайдено в TMDb або у вашій базі даних.")

    popular_movies_display = []
    # Показуємо популярні фільми тільки якщо не було пошукового запиту або пошук нічого не повернув
    if not query or not search_results:
        # Отримуємо всі фільми і сортуємо за рейтингом. Можливо, варто додати фільтр за мінімальною кількістю голосів.
        all_popular_movies_from_db = Movie.objects.all().order_by('-vote_average')

        # Обмежуємо до перших 100 фільмів для пагінації, щоб уникнути надто великих запитів
        movies_to_paginate = all_popular_movies_from_db[:100]

        paginator = Paginator(movies_to_paginate, 20)  # 20 фільмів на сторінку

        page_number = request.GET.get('page_popular', 1)

        try:
            popular_movies_display = paginator.page(page_number)
        except PageNotAnInteger:
            # Якщо номер сторінки не є цілим числом, показати першу сторінку
            popular_movies_display = paginator.page(1)
        except EmptyPage:
            # Якщо номер сторінки виходить за межі, показати останню сторінку
            popular_movies_display = paginator.page(paginator.num_pages)

    user_recommendations = []
    if request.user.is_authenticated:
        # Додано select_related('movie') для оптимізації запитів
        user_recommendations = UserRecommendation.objects.filter(user=request.user).select_related('movie').order_by(
            '-score')[:20]
        if not user_recommendations:
            messages.info(request,
                          "У вас ще немає персональних рекомендацій або вони застаріли. Спробуйте згенерувати їх на сторінці 'Мої рекомендації'.")

    context = {
        'search_results': search_results,
        'popular_movies_page_obj': popular_movies_display,
        'user_recommendations': user_recommendations,
        'query': query,
    }
    return render(request, 'index.html', context)


def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request,
                             'Ви успішно зареєструвалися! Тепер ви можете оцінювати фільми та отримувати рекомендації.')
            return redirect('index')
        else:
            messages.error(request,
                           'Будь ласка, виправте помилки реєстрації. Можливо, ім\'я користувача вже зайняте або пароль занадто простий.')
    else:
        form = CustomUserCreationForm()
    return render(request, 'register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Ласкаво просимо, {user.username}!')
            return redirect('index')
        else:
            messages.error(request, 'Невірне ім\'я користувача або пароль.')
    else:
        form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, 'Ви успішно вийшли з системи.')
    return redirect('index')


@login_required
def account_view(request):
    # Отримуємо ВСІ оцінки користувача, без обмеження [:20]
    user_ratings = Rating.objects.filter(user=request.user).select_related('movie').order_by('-created_at')

    user_recommendations = UserRecommendation.objects.filter(user=request.user).select_related('movie').order_by(
        '-score')[:20] # Рекомендації можна залишити обмеженими, якщо їх багато

    context = {
        'user': request.user,
        'user_ratings': user_ratings,
        'user_recommendations': user_recommendations,
    }
    return render(request, 'account.html', context)


def movie_detail_view(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    user_rating = None
    if request.user.is_authenticated:
        user_rating = Rating.objects.filter(user=request.user, movie=movie).first()

    # Обчислення середнього рейтингу, якщо він існує
    avg_rating_data = movie.ratings.aggregate(avg_score=Avg('score'))
    avg_rating = avg_rating_data['avg_score']



    context = {
        'movie': movie,
        'user_rating': user_rating,
        'avg_rating': round(avg_rating, 1) if avg_rating is not None else None,  # Округлення середнього рейтингу
        'poster_url': movie.poster_url,
        'backdrop_url': get_movie_poster_url(movie.backdrop_path, size='w1280'),
        # 'genres_display_names': movie.genres_display, # Можете залишити, якщо шаблон очікує таку назву
                                                         # але краще використовувати {{ movie.genres_display }} напряму в HTML
    }
    return render(request, 'movie_detail.html', context)


@login_required
def rate_movie(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    if request.method == 'POST':
        score_str = request.POST.get('score')
        if score_str:
            try:
                score = int(score_str)
                if 1 <= score <= 10:
                    Rating.objects.update_or_create(
                        user=request.user,
                        movie=movie,
                        defaults={'score': score}
                    )
                    messages.success(request, f"Ви оцінили фільм '{movie.title}' на {score}/10.")
                else:
                    messages.error(request, "Оцінка повинна бути від 1 до 10.")
            except ValueError:
                messages.error(request, "Невірний формат оцінки. Будь ласка, введіть ціле число.")
        else:
            messages.error(request, "Будь ласка, оберіть оцінку.")
    return redirect('movie_detail', movie_id=movie.id)


@login_required
def delete_rating(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    rating = Rating.objects.filter(user=request.user, movie=movie).first()
    if rating:
        rating.delete()
        messages.info(request, f"Ваша оцінка для фільму '{movie.title}' була видалена.")
    else:
        messages.warning(request, "Ви не оцінювали цей фільм.")
    return redirect('movie_detail', movie_id=movie.id)


def search_movies(request):
    query = request.GET.get('query')
    results = []
    if query:
        tmdb_results = search_movies_tmdb(query)
        for tmdb_movie in tmdb_results:
            movie = import_movie_from_tmdb(tmdb_movie['id'])
            if movie:
                results.append(movie)
        if not results:
            messages.info(request, f"За запитом '{query}' нічого не знайдено.")
    return render(request, 'search_results.html', {'query': query, 'results': results})


@login_required
def user_recommendations_view(request):
    recommendations = UserRecommendation.objects.filter(user=request.user).select_related('movie').order_by('-score')
    return render(request, 'user_recommendations.html', {'recommendations': recommendations})


@login_required
def generate_recommendations_page_view(request):
    if request.method == 'POST':
        logger.info(
            f"User {request.user.username} (ID: {request.user.id}) manually triggered recommendation generation from webpage.")
        # Завдання Celery запускається з параметрами user_id та force_retrain
        generate_recommendations_task.delay(user_id=request.user.id)  # force_retrain за замовчуванням False
        messages.info(request,
                      'Генерація рекомендацій розпочата. Будь ласка, зачекайте кілька хвилин. Вони з\'являться на цій сторінці.')
        return redirect('user_recommendations')

    return render(request, 'generate_recommendations.html')


@login_required
def delete_all_user_recommendations(request):
    if request.method == 'POST':
        user = request.user
        count, _ = UserRecommendation.objects.filter(user=user).delete()
        if count > 0:
            messages.success(request, f"Успішно видалено {count} ваших рекомендацій.")
        else:
            messages.info(request, "Не знайдено рекомендацій для видалення.")
        return redirect('user_recommendations')
    else:
        messages.error(request, "Невірний метод запиту. Використовуйте POST для видалення рекомендацій.")
        return redirect('user_recommendations')


@login_required
def delete_user_recommendation(request, recommendation_id):
    recommendation = get_object_or_404(UserRecommendation, id=recommendation_id, user=request.user)

    if request.method == 'POST':
        recommendation.delete()
        messages.info(request, f"Рекомендація для фільму '{recommendation.movie.title}' була видалена.")
    else:
        messages.warning(request, "Невірний метод запиту для видалення. Використовуйте POST.")

    return redirect('user_recommendations')


# --- API Views (Django REST Framework) ---

class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return User.objects.all()
        return User.objects.filter(id=self.request.user.id)


class MovieViewSet(viewsets.ModelViewSet):
    queryset = Movie.objects.all()
    serializer_class = MovieSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    @action(detail=False, methods=['get'])
    def search(self, request):
        query = request.query_params.get('query', None)
        if not query:
            return Response({"error": "Параметр 'query' є обов'язковим."}, status=status.HTTP_400_BAD_REQUEST)

        tmdb_results = search_movies_tmdb(query)

        movies = []
        for tmdb_movie_data in tmdb_results:
            movie = import_movie_from_tmdb(tmdb_movie_data['id'])
            if movie:
                movies.append(movie)
        serializer = self.get_serializer(movies, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def import_from_tmdb(self, request):
        tmdb_id = request.data.get('tmdb_id')
        if not tmdb_id:
            return Response({"error": "TMDB ID є обов'язковим."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            tmdb_id = int(tmdb_id)
        except ValueError:
            return Response({"error": "Невірний TMDB ID. Повинен бути цілим числом."},
                            status=status.HTTP_400_BAD_REQUEST)

        movie = import_movie_from_tmdb(tmdb_id)
        if movie:
            serializer = self.get_serializer(movie)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        logger.error(f"Failed to import movie with TMDB ID {tmdb_id}.")
        return Response({"error": "Не вдалося імпортувати фільм."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RatingViewSet(viewsets.ModelViewSet):
    queryset = Rating.objects.all()
    serializer_class = RatingSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        rating = serializer.save(user=self.request.user)
        messages.success(self.request, f"Ви оцінили фільм '{rating.movie.title}' на {rating.score}/10.")

    def perform_update(self, serializer):
        rating = serializer.save(user=self.request.user)
        messages.success(self.request, f"Ви оновили оцінку для фільму '{rating.movie.title}' на {rating.score}/10.")

    def perform_destroy(self, instance):
        movie_title = instance.movie.title
        instance.delete()
        messages.info(self.request, f"Оцінку для фільму '{movie_title}' видалено.")

    def get_queryset(self):
        if self.request.user.is_staff:
            return Rating.objects.all()
        return Rating.objects.filter(user=self.request.user)


class UserRecommendationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserRecommendation.objects.all()
    serializer_class = RecommendationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserRecommendation.objects.filter(user=self.request.user).order_by('-score')

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def latest(self, request):
        latest_recommendations = UserRecommendation.objects.filter(user=self.request.user).order_by('-created_at')[:10]
        serializer = self.get_serializer(latest_recommendations, many=True)
        return Response(serializer.data)