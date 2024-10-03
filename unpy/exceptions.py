__all__ = ("StubError", "StubSyntaxError")


class StubError(Exception):
    pass


class StubSyntaxError(SyntaxError):
    pass
