"""Focused tests for typed tool registration and ToolRouter delegation."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from bmo.features import (
    DuplicateToolError,
    ToolContract,
    ToolRegistry,
    UnknownToolError,
)
from bmo.tools import ToolRouter


class ToolRegistryTests(unittest.TestCase):
    def test_executes_canonical_actions_and_aliases(self) -> None:
        handler = Mock(return_value="TOOL RESPONSE")
        registry = ToolRegistry(
            [ToolContract("status", handler, aliases=("check_status",))]
        )

        request = {"action": "  CHECK_STATUS  ", "value": "details"}

        self.assertEqual(registry.normalize_action(request), "status")
        self.assertEqual(registry.execute(request), "TOOL RESPONSE")
        handler.assert_called_once_with(
            {"action": "status", "value": "details"}
        )
        self.assertEqual(registry.actions, {"status"})
        self.assertEqual(registry.aliases, {"check_status": "status"})

    def test_rejects_duplicate_action_names_without_partial_registration(
        self,
    ) -> None:
        first = ToolContract("status", Mock(), aliases=("state",))
        registry = ToolRegistry([first])

        with self.assertRaisesRegex(
            DuplicateToolError,
            "Duplicate tool action name 'status'",
        ):
            registry.register(ToolContract(" STATUS ", Mock()))

        self.assertEqual(registry.actions, {"status"})
        self.assertEqual(registry.aliases, {"state": "status"})

    def test_rejects_duplicate_aliases_without_partial_registration(
        self,
    ) -> None:
        registry = ToolRegistry(
            [ToolContract("status", Mock(), aliases=("inspect",))]
        )

        with self.assertRaisesRegex(
            DuplicateToolError,
            "Duplicate tool alias 'inspect'",
        ):
            registry.register(
                ToolContract("health", Mock(), aliases=("ready", "inspect"))
            )

        self.assertEqual(registry.actions, {"status"})
        self.assertNotIn("ready", registry.aliases)

    def test_rejects_action_and_alias_namespace_collisions(self) -> None:
        registry = ToolRegistry(
            [ToolContract("status", Mock(), aliases=("inspect",))]
        )

        with self.assertRaisesRegex(
            DuplicateToolError,
            "action name 'inspect' conflicts with an alias",
        ):
            registry.register(ToolContract("inspect", Mock()))

        with self.assertRaisesRegex(
            DuplicateToolError,
            "alias 'status' conflicts with the registered action name",
        ):
            registry.register(
                ToolContract("health", Mock(), aliases=("status",))
            )

    def test_unknown_actions_raise_a_clear_error(self) -> None:
        registry = ToolRegistry()

        with self.assertRaisesRegex(
            UnknownToolError,
            "No tool is registered for action 'missing'",
        ):
            registry.execute({"action": "missing"})


class ToolRouterRegistryDelegationTests(unittest.TestCase):
    @staticmethod
    def make_router() -> ToolRouter:
        return ToolRouter({"online_timeout_seconds": 6})

    def test_registered_action_execution_delegates_to_registry(self) -> None:
        router = self.make_router()
        router.registry = Mock()
        router.registry.execute.return_value = "REGISTRY RESPONSE"

        self.assertEqual(
            router.execute({"action": "check_time"}),
            "REGISTRY RESPONSE",
        )
        router.registry.execute.assert_called_once_with(
            {"action": "check_time"}
        )

    def test_camera_trigger_remains_outside_registry(self) -> None:
        router = self.make_router()
        router.registry = Mock()

        self.assertEqual(
            router.execute({"action": "look"}),
            "IMAGE_CAPTURE_TRIGGERED",
        )
        router.registry.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
