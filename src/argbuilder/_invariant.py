"""Panics: the library's way of reporting bugs in the *caller's* program."""

from __future__ import annotations

from typing import NoReturn, TypeAliasType, get_args


def bug(message: str) -> NoReturn:
    """Crash: a state the contract forbids was reached.

    Raised explicitly rather than with `assert`, so `python -O` cannot strip
    it. Never catch this; fix the definition or call site it names.
    """
    raise AssertionError(message)


def invariant(condition: bool, message: str) -> None:
    if not condition:
        bug(message)


def variant_classes(alias: TypeAliasType) -> tuple[type, ...]:
    """The classes of a union alias, following nested aliases: `A | (B | C)` -> `(A, B, C)`."""
    classes: list[type] = []
    pending: list[object] = [alias]
    while pending:
        item = pending.pop(0)
        if isinstance(item, TypeAliasType):
            pending[:0] = get_args(item.__value__) or [item.__value__]
        elif isinstance(item, type):
            classes.append(item)
        else:
            bug(f"{alias.__name__} must be a union of classes, found {item!r}")
    return tuple(classes)


def check_variant(
    value: object, classes: tuple[type, ...], union_name: str, what: str
) -> None:
    """Panic unless `value` is an instance of one of the union's variant classes.

    Passing the class itself (`DisplayHelp` for `DisplayHelp()`) is the easy
    mistake with unit variants, so it gets its own hint.
    """
    if isinstance(value, type) and issubclass(value, classes):
        call = (
            f"{value.__name__}({'...' if getattr(value, '__match_args__', ()) else ''})"
        )
        bug(f"{what}: pass {call}, an instance, not the class {value.__name__}")
    invariant(
        isinstance(value, classes), f"{what} must be an {union_name}, got {value!r}"
    )
