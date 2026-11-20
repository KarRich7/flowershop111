import logging

from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler

from apps.core.errors import DomainError

logger = logging.getLogger(__name__)


def error_response(code, message, http_status=400, details=None):
    return Response({"error": {"code": code, "message": message, "details": details or {}}}, status=http_status)


def exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return error_response(exc.code, exc.message, exc.http_status, exc.details)
    if isinstance(exc, Http404):
        return error_response("not_found", "Не найдено", 404)
    if isinstance(exc, (KeyError, ValueError, TypeError)) and not isinstance(exc, exceptions.APIException):
        logger.info("Bad request: %r", exc)
        return error_response("bad_request", "Некорректные данные запроса", 400)
    response = drf_handler(exc, context)
    if response is None:
        logger.exception("Unhandled error", exc_info=exc)
        return error_response("server_error", "Внутренняя ошибка сервера", status.HTTP_500_INTERNAL_SERVER_ERROR)
    messages = {
        exceptions.NotAuthenticated: "Требуется вход в систему",
        exceptions.AuthenticationFailed: None,
        exceptions.PermissionDenied: "Недостаточно прав",
        exceptions.Throttled: "Слишком много запросов, попробуйте позже",
    }
    message = next((m for cls, m in messages.items() if isinstance(exc, cls) and m), None)
    if not message:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        message = str(detail or "Ошибка запроса")
    return error_response(getattr(exc, "default_code", "error"), message, response.status_code,
                          response.data if not isinstance(response.data, dict) or "detail" not in response.data else {})
