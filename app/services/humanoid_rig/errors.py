"""Failures the caller can act on: a mesh that is not a riggable humanoid, or unusable inputs."""


class NotHumanoid(ValueError):
    """Raised instead of publishing a skeleton that does not match the mesh.

    ``reason`` is a stable motive code. The message always starts with
    ``not_humanoid`` so callers can surface it without parsing the motive.
    """

    code = "not_humanoid"

    def __init__(self, reason: str) -> None:
        self.reason = str(reason)
        super().__init__(f"not_humanoid: {self.reason}")


class InvalidInput(ValueError):
    """The request or one of its files cannot be used as given (wrong format, no animation, unknown clip).

    Unlike a crash, the same request will fail the same way, so callers report it instead of retrying.
    """

    code = "invalid_input"
