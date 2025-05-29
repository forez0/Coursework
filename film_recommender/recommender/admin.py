from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Movie, Rating, UserRecommendation

admin.site.register(User, UserAdmin) # Реєструємо кастомну модель користувача з адмін-панеллю Django
admin.site.register(Movie)
admin.site.register(Rating)
admin.site.register(UserRecommendation)