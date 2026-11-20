from django.contrib import admin

from .models import InventoryItem, StockBalance, StockMovement

admin.site.register(InventoryItem)
admin.site.register(StockBalance)
admin.site.register(StockMovement)
