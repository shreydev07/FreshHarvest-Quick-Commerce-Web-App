
from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def human_weight(value):
    """For kg-based products: display as 'X kg Y g' when fractional, else integer 'X kg'."""
    try:
        v = Decimal(value or 0)
    except Exception:
        return value
    kg = int(v.quantize(Decimal('1.'), rounding='ROUND_DOWN'))
    grams = int((v - kg) * 1000)
    if grams <= 0:
        return f"{kg} kg"
    return f"{kg} kg {grams} g"