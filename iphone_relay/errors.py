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
