from django.db import models
from decimal import Decimal
from django.utils import timezone
from django.conf import settings

class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    def __str__(self):
        return self.name

class Unit(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

class Product(models.Model):
    title = models.CharField(max_length=255)
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    description = models.TextField(blank=True)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    published_date = models.DateField(null=True, blank=True)
    cover_image = models.ImageField(upload_to='product_images/', blank=True, null=True)
    # change: use decimal stock so fractional kg/ltr works
    stock = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))
    # optional maximum / capacity used for percentage calculation (if 0 then treated as 100% when stock >0)
    max_stock = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'))
    # new: enable per-product sub-quantities (variants like 250g/500g)
    subquantity_enabled = models.BooleanField(default=False)   # allow per-product subunits
    last_stock_update = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title

class StockHistory(models.Model):
    """
    Log of stock changes: positive amount = added, negative = deducted.
    amount stored in same base unit as Product.stock
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_history')
    amount = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.CharField(max_length=200, blank=True)  # e.g. 'order #ORD000123', 'admin add'
    created_at = models.DateTimeField(auto_now_add=True)
    admin_user = models.CharField(max_length=100, blank=True, null=True)  # optional admin id who changed

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product.title}: {self.amount} @ {self.created_at}"

class Offer(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # new datetime fields (admin can set date+time)
    start_datetime = models.DateTimeField(null=True, blank=True)
    end_datetime = models.DateTimeField(null=True, blank=True)

    # keep legacy date columns (DB currently has start_date / end_date). allow null but keep them in-sync
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} ({self.start_datetime} → {self.end_datetime})"

    def is_active(self):
        now = timezone.now()
        if not self.active:
            return False
        if self.start_datetime and self.end_datetime:
            return self.start_datetime <= now <= self.end_datetime
        # fallback to date fields if datetime not set
        today = timezone.localdate()
        if self.start_date and self.end_date:
            return self.start_date <= today <= self.end_date
        return False

    def save(self, *args, **kwargs):
        # keep date fields synced with datetime fields to satisfy existing DB columns
        try:
            if self.start_datetime and not self.start_date:
                self.start_date = self.start_datetime.date()
            if self.end_datetime and not self.end_date:
                self.end_date = self.end_datetime.date()
        except Exception:
            pass
        super().save(*args, **kwargs)

class OfferItem(models.Model):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    offer_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    unlisted = models.BooleanField(default=False)

    class Meta:
        unique_together = ('offer', 'product')

    def __str__(self):
        return f"{self.product.title} @ {self.offer_price} ({self.offer.title})"

def get_active_offer_price(product):
    now = timezone.now()
    oi = OfferItem.objects.filter(
        product=product,
        unlisted=False,
        offer__active=True,
        offer__start_datetime__lte=now,
        offer__end_datetime__gte=now
    ).select_related('offer').order_by('-offer__start_datetime').first()
    if oi:
        return (oi.offer_price, oi)
    return (product.price, None)

class StockAlert(models.Model):
    ALERT_LOW = 'low'
    ALERT_OUT = 'out'
    ALERT_TYPES = [
        (ALERT_LOW, 'Low Stock'),
        (ALERT_OUT, 'Out Of Stock'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=10, choices=ALERT_TYPES)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    viewed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product.title} - {self.alert_type} @ {self.created_at}"

class UnitSubUnit(models.Model):
    """
    Sub-units defined per Unit (global templates like 250g => 0.25 kg).
    Admin can add multiple sub-units for a Unit; products using that Unit can opt-in to allow any subset.
    """
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='subunits')
    name = models.CharField(max_length=50)                # "250g", "500g"
    factor_to_base = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal('0.001'))
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ('unit', 'name')
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.unit.name} - {self.name}"

class ProductSubQuantity(models.Model):
    """
    A small variant attached to a product (e.g. "250gm" -> factor 0.25 if product stored in kg).
    admin can specify a price for the subquantity (optional) — if empty, price will be computed
    from product.price * factor.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='subquantities')
    name = models.CharField(max_length=50)              # e.g. '250gm', '500gm'
    factor_to_base = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal('0.001'))
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # link to a unit-level subunit when created from UnitSubUnit (optional)
    unit_subunit = models.ForeignKey(UnitSubUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name='product_variants')
    # ordering
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ('product', 'name')
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.product.title} - {self.name}"



