"""Opt-in BMO iMessage Relay feature and service plugin."""

from .feature import (
    DEFAULT_RECEIVER_CONFIG_PATH,
    DEFAULT_RELAY_CONFIG_PATH,
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

__all__ = [
    "DEFAULT_RECEIVER_CONFIG_PATH",
    "DEFAULT_RELAY_CONFIG_PATH",
    "IMESSAGE_RELAY_MENU_ITEM",
    "IMessageRelayTool",
    "RelayFeatureConfig",
    "RelayRuntimeService",
    "RelayRuntimeStatus",
    "load_feature_config",
    "register",
    "register_menu_metadata",
    "register_metadata",
]
