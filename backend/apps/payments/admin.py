from django.contrib import admin

from .models import Payment, PaymentWebhookEvent

admin.site.register(Payment)
admin.site.register(PaymentWebhookEvent)
