from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, ShopSettings, User


@admin.register(User)
class StaffAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Магазин", {"fields": ("role", "phone", "is_demo")}),)
    list_display = ("username", "first_name", "last_name", "role", "is_active")


admin.site.register(ShopSettings)
admin.site.register(AuditLog)
