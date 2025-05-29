# recommender/templatetags/custom_filters.py
from django import template
from ..utils import get_movie_poster_url
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def split_and_badge(value, separator=','):
    """
    Splits a string by a separator and wraps each part in a Bootstrap badge.
    Assumes 'value' is a string like "Action, Drama, Comedy".
    """
    if not value:
        return ""
    parts = [part.strip() for part in value.split(separator) if part.strip()]
    badges_html = [f'<span class="badge bg-secondary me-1">{part}</span>' for part in parts]
    return mark_safe(" ".join(badges_html))


@register.filter
def safe_poster_url(poster_path, size='w500'):
    return get_movie_poster_url(poster_path, size)