class DomainError(Exception):
    """Ошибка бизнес-логики с понятным пользователю сообщением."""

    code = "domain_error"
    http_status = 400

    def __init__(self, message, code=None, details=None, http_status=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status
        self.details = details or {}


class PermissionDenied(DomainError):
    code = "forbidden"
    http_status = 403


class NotFound(DomainError):
    code = "not_found"
    http_status = 404


class ValidationError(DomainError):
    code = "validation_error"


class ConflictError(DomainError):
    code = "conflict"
    http_status = 409
