# recommender/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views # <-- KEEP THIS ONE! This correctly imports everything from views.py
# from views import delete_all_user_recommendations # <-- REMOVE THIS LINE! It's causing the error.

# DRF Router для API ViewSets
router = DefaultRouter()
# Важливо: 'users' ViewSet зазвичай не реєструється напряму, якщо ви використовуєте CustomUserCreationForm
# і управляєте реєстрацією через стандартні Django View.
# Якщо у вас є API для User, переконайтеся, що він правильно налаштований.
# Можливо, вам не потрібен views.UserViewSet, якщо ви використовуєте лише вбудовані форми Django для користувачів.
# router.register(r'users', views.UserViewSet) # Можливо, закоментуйте або видаліть, якщо не використовуєте API для User
router.register(r'movies', views.MovieViewSet)
router.register(r'ratings', views.RatingViewSet)
router.register(r'recommendations', views.UserRecommendationViewSet, basename='user_recommendation') # Використовуйте basename

urlpatterns = [
    # --- Веб-сторінки та користувацький інтерфейс ---
    path('', views.index, name='index'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('account/', views.account_view, name='account'),
    path('movie/<int:movie_id>/', views.movie_detail_view, name='movie_detail'),
    path('rate_movie/<int:movie_id>/', views.rate_movie, name='rate_movie'),
    path('delete_rating/<int:movie_id>/', views.delete_rating, name='delete_rating'),
    path('search_movies/', views.search_movies, name='search_movies'),
    path('user_recommendations/', views.user_recommendations_view, name='user_recommendations'),
    path('delete_recommendation/<int:recommendation_id>/', views.delete_user_recommendation, name='delete_user_recommendation'),
    path('delete-all-recommendations/', views.delete_all_user_recommendations, name='delete_all_user_recommendations'), # <-- Use views.delete_all_user_recommendations
    # --- НОВИЙ МАРШРУТ ДЛЯ ГЕНЕРАЦІЇ РЕКОМЕНДАЦІЙ З HTML-СТОРІНКИ ---
    # Цей маршрут буде обробляти POST-запит для запуску Celery-задачі
    path('generate_recommendations/', views.generate_recommendations_page_view, name='generate_recommendations_page'),

    # --- API ендпоінти Django REST Framework ---
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
]