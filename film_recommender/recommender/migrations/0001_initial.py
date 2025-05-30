# Generated by Django 5.2.1 on 2025-05-26 21:01

import django.contrib.auth.models
import django.contrib.auth.validators
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='Movie',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tmdb_id', models.IntegerField(unique=True)),
                ('title', models.CharField(max_length=255)),
                ('overview', models.TextField(blank=True, null=True)),
                ('release_date', models.DateField(blank=True, null=True)),
                ('poster_path', models.CharField(blank=True, max_length=255, null=True)),
                ('poster_url', models.URLField(blank=True, max_length=500, null=True)),
                ('backdrop_path', models.CharField(blank=True, max_length=255, null=True)),
                ('backdrop_url', models.URLField(blank=True, max_length=500, null=True)),
                ('vote_average', models.FloatField(default=0.0)),
                ('vote_count', models.IntegerField(default=0)),
                ('genres_json', models.JSONField(blank=True, default=list, null=True)),
                ('directors_json', models.JSONField(blank=True, default=list, null=True)),
                ('cast_json', models.JSONField(blank=True, default=list, null=True)),
                ('production_countries_json', models.JSONField(blank=True, default=list, null=True)),
                ('spoken_languages_json', models.JSONField(blank=True, default=list, null=True)),
                ('keywords_json', models.JSONField(blank=True, default=list, null=True)),
            ],
            options={
                'verbose_name': 'Movie',
                'verbose_name_plural': 'Movies',
                'ordering': ['title'],
            },
        ),
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'abstract': False,
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Rating',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.IntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10)])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('movie', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ratings', to='recommender.movie')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ratings', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Rating',
                'verbose_name_plural': 'Ratings',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['user'], name='recommender_user_id_c34a3c_idx'), models.Index(fields=['movie'], name='recommender_movie_i_aef780_idx'), models.Index(fields=['score'], name='recommender_score_8c4317_idx')],
                'unique_together': {('user', 'movie')},
            },
        ),
        migrations.CreateModel(
            name='UserRecommendation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('movie', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='recommender.movie')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_recommendations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'User Recommendation',
                'verbose_name_plural': 'User Recommendations',
                'ordering': ['-score'],
                'indexes': [models.Index(fields=['user'], name='recommender_user_id_67d662_idx'), models.Index(fields=['movie'], name='recommender_movie_i_9c53df_idx'), models.Index(fields=['score'], name='recommender_score_bc0d65_idx')],
                'unique_together': {('user', 'movie')},
            },
        ),
    ]
