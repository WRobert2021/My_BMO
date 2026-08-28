# Generic Vision Follow-Up

owner: feature contracts, `bmo.conversation.ToolResultPresenter`, and
`RuntimeExtensionCoordinator`

Executable tools return a typed image attachment and/or `ToolFollowUp` of kind
`VISION`. Open feature views use `FeatureMenuContext.request_vision(Path,
completion)`. The runtime validates the path type, queues work to the normal
interaction worker, invokes the configured vision model, and posts completion
back to the presentation thread.

The interface does not expose model objects, archives, or the application
coordinator to plugins. Vision text is presentation-only even when a model
formats it like JSON or prefixes it with `Action:`; it must not be reinterpreted
as another tool call. If the requester is closing, it must invalidate or safely
handle late completion. If the runtime did not provide a vision requester, the
UI action must be disabled or report unavailable rather than crash core plugin
behavior.

Consumers: Capture Image (typed tool result) and Album (menu action). Tests:
`tests/test_camera.py`, `tests/test_album.py`,
`tests/test_tool_presentation.py`, and `tests/test_runtime_extensions.py`.
