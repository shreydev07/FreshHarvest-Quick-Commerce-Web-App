from django.db import models
from mainapp.models import UserInfo
from adminapp.models import Product, ProductSubQuantity
from decimal import Decimal

class Cart(models.Model):
    user = models.OneToOneField(UserInfo, on_delete=models.CASCADE)

    def __str__(self):
        return f"Cart({self.user.email})"

class CartItem(models.Model):
    cart = models.ForeignKey('Cart', on_delete=models.CASCADE)
    product = models.ForeignKey('adminapp.Product', on_delete=models.CASCADE)
    # quantity is number of units (if variant selected, number of variant units; if no variant, qty in base unit e.g. kg)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('1.000'))
    # optional variant selection
    variant = models.ForeignKey('adminapp.ProductSubQuantity', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.product.title} x {self.quantity}"

    def get_total_price(self):
        # price for variant if set, else derived from product.price * factor
        price = None
        if self.variant and self.variant.price is not None:
            price = self.variant.price
        else:
            # product.price is per-base-unit (e.g. per kg)
            if self.variant and self.variant.factor_to_base:
                # price = product.price * factor_to_base
                price = (self.product.price or Decimal('0')) * Decimal(self.variant.factor_to_base)
            else:
                price = (self.product.price or Decimal('0')) * Decimal(self.quantity)
        return (Decimal(price) * Decimal(self.quantity)) if (price is not None) else Decimal('0.00')

class Order(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_TRANSIT = 'transit'
    STATUS_DISPATCHED = 'dispatched'
    STATUS_CANCELLED = 'cancelled'
    STATUS_DELIVERED = 'delivered'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_TRANSIT, 'In Transit'),
        (STATUS_DISPATCHED, 'Dispatched'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_DELIVERED, 'Delivered'),
    ]

    user = models.ForeignKey(UserInfo, on_delete=models.CASCADE)
    order_number = models.CharField(max_length=30, unique=True, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ordered_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    def __str__(self):
        return self.order_number or f"Order {self.id}"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.order_number:
            # create stable prefixed order number (zero-padded)
            self.order_number = f"ORD{self.id:06d}"
            super().save(update_fields=['order_number'])

class OrderItem(models.Model):
    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('adminapp.Product', on_delete=models.SET_NULL, null=True)
    # change to DecimalField to support fractional units when variant not present; quantity semantics:
    # - if variant set: quantity = number of variant units (integer or decimal)
    # - if variant not set: quantity = amount in base units (e.g. kg)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('1.000'))
    variant = models.ForeignKey('adminapp.ProductSubQuantity', on_delete=models.SET_NULL, null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))  # snapshot price at order time

    def get_total_price(self):
        return (self.price or Decimal('0.00')) * (self.quantity or Decimal('0.000'))
