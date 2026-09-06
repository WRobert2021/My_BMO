"""Opt-in BMO iMessage Relay feature and service plugin."""

from .feature import (
    DEFAULT_PHONE_CONTROL_CONFIG_PATH,
    DEFAULT_RECEIVER_CONFIG_PATH,
    IMESSAGE_RELAY_MENU_ITEM,
    IMessageRelayTool,
    RelayFeatureConfig,
    RelayRuntimeService,
    RelayRuntimeStatus,
    load_feature_config,
    register,
    register_menu_metadata,
    register_metadata,
)
from .notifications import (
    NotificationCountError,
    new_message_count,
    received_message_count,
)

__all__ = [
    "DEFAULT_PHONE_CONTROL_CONFIG_PATH",
    "DEFAULT_RECEIVER_CONFIG_PATH",
    "IMESSAGE_RELAY_MENU_ITEM",
    "IMessageRelayTool",
    "NotificationCountError",
    "RelayFeatureConfig",
    "RelayRuntimeService",
    "RelayRuntimeStatus",
    "load_feature_config",
    "new_message_count",
    "received_message_count",
    "register",
    "register_menu_metadata",
    "register_metadata",
]
