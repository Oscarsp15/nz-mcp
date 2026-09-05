"""Credential values that never render themselves in plain text.

Why this exists: Python renders a traceback frame together with the **arguments** of
that frame. pytest does it by default (``--tb=long`` prints ``password = 'hunter2'``),
and so do IPython, Sentry and any ``--showlocals``-style renderer. A password carried
around as a plain ``str`` therefore leaks on any failure in the connection path, going
around ``logging_utils.sanitize`` entirely: the sanitizer only sees the strings we build,
never the frames the interpreter prints.

``Secret`` is a ``str`` **subclass** on purpose. It keeps flowing through third-party
code (``nzpy`` does ``isinstance(password, str)`` and ``password.encode('utf8')``) with
no adapter and no unwrapping at the call site, so the redaction also covers the driver's
own frames, which is where most of the leaked copies live. Every rendering hook is
redacted: ``repr``, ``str``, ``format`` and ``encode`` -- the last one because ``nzpy``
re-binds its ``password`` argument to the encoded value, and plain ``bytes`` would put
the credential back into a frame.

What it does **not** protect: values *derived* from a secret (``secret[:4]``,
``secret + "x"``, ``json.dumps(secret)``) are plain ``str``/``bytes`` again. Rendering
protection is the first barrier; ``sanitize(..., known_secrets={password})`` stays the
second one for the text we build ourselves.

See ``docs/adr/0026-secret-sin-password-en-trazas.md``.
"""

from __future__ import annotations

from typing import Final

REDACTED: Final[str] = "***"


class SecretBytes(bytes):
    """Encoded form of a :class:`Secret`: real bytes, redacted rendering."""

    __slots__ = ()

    def __new__(cls, value: bytes = b"") -> SecretBytes:
        # Not the same trap as ``Secret.__new__``: ``bytes.__new__`` copies the buffer
        # and never renders through ``__repr__``, so rebuilding from a ``SecretBytes``
        # was already correct. This exists to keep that guarantee explicit and to
        # survive a future ``__bytes__`` override on this class.
        return super().__new__(cls, memoryview(value).tobytes())

    def __repr__(self) -> str:
        return f"SecretBytes({REDACTED})"

    def __str__(self) -> str:
        return REDACTED

    def reveal(self) -> bytes:
        """Return the plain bytes. Use only where the real value is required."""
        return bytes(self)


class Secret(str):
    """A ``str`` holding a credential that renders as ``***`` everywhere.

    Equality, hashing, slicing and encoding still operate on the real value, so it is a
    drop-in replacement for the ``str`` that the driver and the sanitizer expect.
    """

    __slots__ = ()

    def __new__(cls, value: str = "") -> Secret:
        # ``str.__new__`` renders its argument with ``str()``, and ``__str__`` is
        # redacted here, so wrapping a ``Secret`` again would store the literal
        # ``***`` and silently destroy the credential. Read the underlying buffer
        # instead. This is not defensive: ``open_connection`` re-binds its argument
        # unconditionally, so double wrapping is the normal path, not an edge case.
        return super().__new__(cls, str.__str__(value) if isinstance(value, str) else value)

    def __repr__(self) -> str:
        return f"Secret({REDACTED})"

    def __str__(self) -> str:
        return REDACTED

    def __format__(self, format_spec: str) -> str:
        # f-strings do not go through __str__ for str subclasses; without this,
        # f"{password}" would print the credential.
        return REDACTED

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> SecretBytes:
        return SecretBytes(str.encode(self, encoding, errors))

    def reveal(self) -> str:
        """Return the plain value. Use only at a boundary that needs the real string."""
        return str.__str__(self)


def reveal(value: str) -> str:
    """Plain text of ``value``, whether or not it is a :class:`Secret`."""
    return value.reveal() if isinstance(value, Secret) else value
