from decimal import Decimal, InvalidOperation

UNIT_TO_BASE = {
    'kg': {'base': 'kg', 'factor': Decimal('1')},
    'pcs': {'base': 'pcs', 'factor': Decimal('1')},
    'ltr': {'base': 'ltr', 'factor': Decimal('1')},
    # add other base units if needed
}

def get_unit_factor_for_product(product):
    """Return factor to convert 1 displayed unit into base stock units (Decimal)."""
    try:
        uname = (product.unit.name or '').strip().lower()
    except Exception:
        uname = ''
    return UNIT_TO_BASE.get(uname, {'factor': Decimal('1')})['factor']

def convert_quantity_to_base(qty, product, variant=None):
    """
    Convert qty to product stock base units (Decimal).
    - qty: Decimal/str/number (quantity of variant units if variant provided; else units of product.unit)
    - variant: ProductSubQuantity instance or id (optional)
    Returns Decimal quantized to 3 dp.
    """
    try:
        q = Decimal(qty)
    except (InvalidOperation, TypeError):
        q = Decimal('0')
    if variant:
        # variant may be id or instance
        try:
            if not hasattr(variant, 'factor_to_base'):
                from .models import ProductSubQuantity
                variant = ProductSubQuantity.objects.get(pk=int(variant))
            factor = Decimal(variant.factor_to_base or '1')
        except Exception:
            factor = Decimal('1')
        return (q * factor).quantize(Decimal('0.001'))
    # no variant: multiply by unit factor (kg -> 1)
    factor = get_unit_factor_for_product(product)
    return (q * Decimal(factor)).quantize(Decimal('0.001'))