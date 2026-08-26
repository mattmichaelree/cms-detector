"""Entity spine: sessions, people, organizations, crosswalks, resolution."""

from contextlib import suppress

# Submodules register their loaders on import; tolerate partial builds while
# the swarm fills these in.
with suppress(ImportError):
    from lobbybook.spine import sessions  # noqa: F401
with suppress(ImportError):
    from lobbybook.spine import people  # noqa: F401
with suppress(ImportError):
    from lobbybook.spine import resolve  # noqa: F401
