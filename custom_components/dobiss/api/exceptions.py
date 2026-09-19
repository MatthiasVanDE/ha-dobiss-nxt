"""Exceptions raised by the Dobiss NXT client."""

from __future__ import annotations


class DobissError(Exception):
    """Base class for every error raised by this client."""


class DobissConnectionError(DobissError):
    """The NXT server could not be reached."""


class DobissAuthError(DobissError):
    """The server rejected our credentials.

    Almost always a wrong API secret, or the developer API not being enabled in
    the NXT settings.
    """


class DobissResponseError(DobissError):
    """The server answered, but not with something we could use."""
