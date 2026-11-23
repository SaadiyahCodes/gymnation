"""One error type; every failure leaves as {"error": {"code", "message", ...}}."""


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}


def validation(message: str) -> ApiError:
    return ApiError(422, "VALIDATION", message)