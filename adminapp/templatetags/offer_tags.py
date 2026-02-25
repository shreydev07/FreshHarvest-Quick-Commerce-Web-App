from django import template

register = template.Library()

@register.filter
def dict_get(d, key):
    """
    Safe dict lookup in templates: {{ mydict|dict_get:key }}
    Accepts numeric or string keys.
    Returns None on error.
    """
    try:
        if d is None:
            return None
        try:
            ik = int(key)
        except Exception:
            ik = None
        if ik is not None and ik in d:
            return d.get(ik)
        return d.get(key)
    except Exception:
        return None