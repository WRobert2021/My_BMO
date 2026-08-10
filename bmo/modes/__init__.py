"""Lifecycle contracts and registry for long-lived interaction modes."""

from bmo.modes.contracts import (
    InputPolicy,
    InputPolicyKind,
    InteractionMode,
    ModeMenuItem,
    ModeRuntimeContext,
)
from bmo.modes.loader import ModeLoadFailure, ModeLoadResult, load_mode_registry
from bmo.modes.registry import DuplicateModeError, ModeRegistry

__all__ = [
    "DuplicateModeError",
    "InputPolicy",
    "InputPolicyKind",
    "InteractionMode",
    "ModeMenuItem",
    "ModeLoadFailure",
    "ModeLoadResult",
    "ModeRegistry",
    "ModeRuntimeContext",
    "load_mode_registry",
]
