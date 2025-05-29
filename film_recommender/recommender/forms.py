from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User


class CustomUserCreationForm(UserCreationForm):
    """
    Кастомна форма для створення нового користувача, яка використовує
    вашу модель recommender.User.
    """
    class Meta(UserCreationForm.Meta):
        model = User
        # Включаємо поля зі стандартної форми та додаємо email
        fields = UserCreationForm.Meta.fields + ('email',)


class CustomUserChangeForm(UserChangeForm):
    """
    Кастомна форма для редагування користувача, яка використовує
    вашу модель recommender.User.
    """
    class Meta(UserChangeForm.Meta):
        model = User
        fields = UserChangeForm.Meta.fields  # або: ('username', 'email', 'first_name', ...)
