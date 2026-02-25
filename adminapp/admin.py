from django.contrib import admin

from mainapp.models import Subscriber
from .models import *
# Register your models here.
admin.site.register(Category)
admin.site.register(Product)
admin.site.register(Unit)
admin.site.register(Offer)
admin.site.register(OfferItem)
admin.site.register(Subscriber)