"""Errors shared by the Twenty Questions dataset and game layers."""


class TwentyQuestionsDataError(ValueError):
    """A base or learned catalog failed validation."""


class LearningPersistenceError(OSError):
    """The learned overlay could not be atomically persisted."""


__all__ = ["LearningPersistenceError", "TwentyQuestionsDataError"]
