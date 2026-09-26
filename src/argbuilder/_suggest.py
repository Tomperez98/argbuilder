"""Closest-match suggestions for mistyped names, shared by the builders and the parser.

One helper, so the "did you mean" wording and the closeness threshold stay
identical whether the typo is in an `Arg.action()` call or on the command line.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def suggest(typed: str, candidates: Iterable[str]) -> str | None:
    """The candidate closest to `typed`, or None when nothing is close enough."""
    matches = difflib.get_close_matches(typed, list(candidates), n=1)
    return matches[0] if matches else None
