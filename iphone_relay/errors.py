"""Domain errors for the read-only iMessage source parser."""


class IMessageParserError(ValueError):
    """Base error for unsupported or unsafe Messages source data."""


class SourceDatabaseError(IMessageParserError):
    """Raised when the source database cannot be opened or queried safely."""


class SourceSchemaError(SourceDatabaseError):
    """Raised when the Messages schema lacks a required Stage 2 column."""


class SourceRecordError(IMessageParserError):
    """Raised when one source row cannot be normalized safely."""


class AttributedBodyError(SourceRecordError):
    """Raised when an attributed-body archive is unsupported or malformed."""


class UnsafeAttachmentPathError(SourceRecordError):
    """Raised when an Apple attachment filename escapes its owned root."""


class RelayStateError(RuntimeError):
    """Base error for relay-owned durable-state failures."""


class StateDatabaseError(RelayStateError):
    """Raised when relay-owned SQLite state cannot be opened or updated."""


class StateConfigError(RelayStateError):
    """Raised when relay-owned state/retry configuration is invalid."""


class StateSecurityError(RelayStateError):
    """Raised when a state path could expose data or target Apple's store."""


class StateSchemaError(RelayStateError):
    """Raised when a relay-owned database has an unsupported schema."""


class StateIntegrityError(RelayStateError):
    """Raised when durable state conflicts with a newly discovered event."""


class CursorConflictError(RelayStateError):
    """Raised when a scan was based on a stale or discontinuous cursor."""


class StateTransitionError(RelayStateError):
    """Raised when a delivery transition is not valid for the stored state."""


class StateClosedError(RelayStateError):
    """Raised when a closed state manager is used."""
