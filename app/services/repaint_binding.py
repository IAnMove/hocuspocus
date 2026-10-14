"""Call-time lookup of launch globals for the Repaint move.

Each Repaint module keeps its own namespace holder. ``bind_once`` fills that
holder from the dict launch passes (its ``globals()``) and refuses a later
bind to a different dict, so a second call cannot hide a wrong first one.
A ``LaunchName`` reads the name when the moved function uses it, which is
after launch has finished defining the later collaborators and after a test
has patched the launch name.
"""


class LaunchName:
    """One launch global, resolved from this module's namespace holder."""

    def __init__(self, namespace: list, name: str) -> None:
        self._namespace = namespace
        self._name = name

    def resolve(self):
        namespace = self._namespace[0]
        if namespace is None:
            raise RuntimeError(
                f"{self._name} is used before its Repaint module was bound to launch"
            )
        return namespace[self._name]

    def __call__(self, *args, **kwargs):
        return self.resolve()(*args, **kwargs)

    def __getattr__(self, item: str):
        return getattr(self.resolve(), item)

    def __getitem__(self, item):
        return self.resolve()[item]

    def __len__(self) -> int:
        return len(self.resolve())

    def __iter__(self):
        return iter(self.resolve())

    def __bool__(self) -> bool:
        return bool(self.resolve())


def bind_once(holder: list, namespace: dict, label: str) -> None:
    """Bind ``holder`` to ``namespace`` once. The same dict may be bound again."""
    current = holder[0]
    if current is None:
        holder[0] = namespace
        return
    if current is not namespace:
        raise RuntimeError(f"{label} is already bound to a different namespace")
