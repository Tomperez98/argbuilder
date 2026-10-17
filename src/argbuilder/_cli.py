"""The process edge: the one place an `Error` becomes text on a stream and an exit code.

Everything above this module is pure or data-only. `Error.exit()`,
`Command.get_matches_from` and the examples all funnel through
`exit_with`, so the stream choice, the styling and the exit status are written
here once, and the domain error value never touches `sys` or a terminal.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, NoReturn

from argbuilder._style import terminal_style

if TYPE_CHECKING:
    from argbuilder._error import Error


def exit_with(error: Error) -> NoReturn:
    """Print `error` styled for its stream and exit with its status code."""
    stream = sys.stderr if error.use_stderr else sys.stdout
    stream.write(error.render(terminal_style(stream)))
    stream.flush()
    sys.exit(error.exit_code)
