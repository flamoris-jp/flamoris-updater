class UpdateError(Exception):
    """A bounded public error. Never attach provider output or credential values."""

    def __init__(self, code: str, message: str = "Operation rejected"):
        super().__init__(message)
        self.code = code
        self.message = message[:1024]

    def public(self) -> dict:
        return {"error": self.code, "message": self.message}
