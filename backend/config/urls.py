from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("api/v1/", include("apps.api.urls")),
    # Медиафайлы (фото букетов). В боевом режиме их отдаёт Caddy напрямую из тома, сюда запрос не доходит.
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]

if settings.DJANGO_ADMIN_ENABLED:
    # Служебная админка Django — только для разработки (в боевом режиме выключена: DJANGO_ADMIN_ENABLED=false).
    urlpatterns.insert(0, path("django-admin/", admin.site.urls))

if settings.API_DOCS_ENABLED:
    # Документация API (Swagger). В боевом режиме по умолчанию скрыта, чтобы не подсказывать устройство сайта.
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    ]
