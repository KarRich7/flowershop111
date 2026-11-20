from django.contrib import admin

from .models import Product, ProductImage


class ImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "category", "is_active")
    inlines = [ImageInline]
