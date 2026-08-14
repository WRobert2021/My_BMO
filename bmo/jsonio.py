"""Shared strict JSON decoding and crash-safe atomic file replacement."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import json
import os
from pathlib import Path
import tempfile
from typing import Any, TextIO


class DuplicateJSONKeyError(ValueError):
    """Raised when a JSON object repeats a field name."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting ambiguous duplicate fields."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def duplicate_key_hook(
    error_factory: Callable[[str], Exception],
    message: str,
) -> Callable[[list[tuple[str, Any]]], dict[str, Any]]:
    """Adapt duplicate-key rejection to a domain-specific exception."""
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise error_factory(message)
            result[key] = value
        return result

    return hook


def reject_json_constant(value: str) -> None:
    """Reject non-finite numbers, which are outside strict JSON."""
    raise ValueError(f"non-finite JSON number {value} is unsupported")


def load_json(handle: Any) -> Any:
    """Decode strict JSON from a text or binary file-like object."""
    return json.load(
        handle,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_json_constant,
    )


def loads_json(value: str | bytes | bytearray) -> Any:
    """Decode strict JSON from a string or bytes value."""
    return json.loads(
        value,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_json_constant,
    )


def first_json_object(value: str) -> dict[str, Any] | None:
    """Return the first strictly valid JSON object embedded in text."""
    if not isinstance(value, str):
        return None
    decoder = json.JSONDecoder(
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_json_constant,
    )
    for index, character in enumerate(value):
        if character != "{":
            continue
        try:
            decoded, _ = decoder.raw_decode(value, index)
        except json.JSONDecodeError:
            continue
        except (DuplicateJSONKeyError, ValueError, TypeError):
            return None
        if isinstance(decoded, dict):
            return decoded
    return None


def atomic_write(
    path: str | Path,
    writer: Callable[[TextIO], None],
    *,
    directory_mode: int | None = None,
    fsync_directory: bool = False,
    replace: Callable[[str | Path, str | Path], None] = os.replace,
) -> None:
    """Flush a temporary file and atomically replace ``path`` with it."""
    destination = Path(path)
    if directory_mode is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination.parent.mkdir(
            mode=directory_mode,
            parents=True,
            exist_ok=True,
        )

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor_open = False
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        replace(temporary, destination)
        if fsync_directory:
            _fsync_directory(destination.parent)
    except Exception:
        if descriptor_open:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(
    path: str | Path,
    value: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    allow_nan: bool = False,
    directory_mode: int | None = None,
    fsync_directory: bool = False,
    replace: Callable[[str | Path, str | Path], None] = os.replace,
) -> None:
    """Serialize JSON with a trailing newline through :func:`atomic_write`."""
    def write(handle: TextIO) -> None:
        json.dump(
            value,
            handle,
            indent=indent,
            ensure_ascii=ensure_ascii,
            allow_nan=allow_nan,
        )
        handle.write("\n")

    atomic_write(
        path,
        write,
        directory_mode=directory_mode,
        fsync_directory=fsync_directory,
        replace=replace,
    )


def atomic_write_json_lines(
    path: str | Path,
    values: Iterable[Any],
    *,
    ensure_ascii: bool = False,
    separators: tuple[str, str] = (",", ":"),
    replace: Callable[[str | Path, str | Path], None] = os.replace,
) -> None:
    """Atomically write one compact JSON value per line."""
    def write(handle: TextIO) -> None:
        for value in values:
            handle.write(
                json.dumps(
                    value,
                    ensure_ascii=ensure_ascii,
                    allow_nan=False,
                    separators=separators,
                )
            )
            handle.write("\n")

    atomic_write(path, write, replace=replace)


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        # The file itself is already flushed and replaced. Some platforms and
        # filesystems do not permit directory fsync.
        pass
