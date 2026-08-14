"""Typed failures shared by Learning persistence components."""


class LearningStoreError(RuntimeError):
    """Base class for expected local Learning persistence failures."""


class LearningCorruptDataError(LearningStoreError):
    """Raised when an existing document cannot safely be interpreted."""


class LearningReadOnlyError(LearningStoreError):
    """Raised when a mutation would overwrite unreadable local data."""


class LearningPersistenceError(LearningStoreError):
    """Raised when a validated mutation cannot be committed durably."""


class LearningConfirmationRequired(LearningStoreError):
    """Raised when a destructive operation lacks explicit confirmation."""


__all__ = [
    "LearningConfirmationRequired",
    "LearningCorruptDataError",
    "LearningPersistenceError",
    "LearningReadOnlyError",
    "LearningStoreError",
]
