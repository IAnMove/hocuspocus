"""Explicit failure when a mesh is not a riggable humanoid."""


class NotHumanoid(ValueError):
    """Raised instead of publishing a skeleton that does not match the mesh.

    ``reason`` is a stable motive code. The message always starts with
    ``not_humanoid`` so callers can surface it without parsing the motive.
    """

    code = "not_humanoid"

    def __init__(self, reason: str) -> None:
        self.reason = str(reason)
        super().__init__(f"not_humanoid: {self.reason}")
