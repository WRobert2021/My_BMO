import unittest

from bmo.tools import ToolRouter


class ToolRoutingTests(unittest.TestCase):
    def test_clear_time_request_routes_directly(self):
        self.assertEqual(
            ToolRouter.match_direct_action("What time is it?"),
            {"action": "get_time"},
        )

    def test_explicit_web_search_routes_directly(self):
        self.assertEqual(
            ToolRouter.match_direct_action("Search the web for robot news."),
            {"action": "search_web", "query": "robot news"},
        )

    def test_look_up_routes_directly(self):
        self.assertEqual(
            ToolRouter.match_direct_action("Look up Raspberry Pi 5 cooling"),
            {"action": "search_web", "query": "raspberry pi 5 cooling"},
        )

    def test_explicit_camera_request_routes_directly(self):
        self.assertEqual(
            ToolRouter.match_direct_action("Take a picture."),
            {"action": "capture_image"},
        )

    def test_empty_search_is_not_routed(self):
        self.assertIsNone(ToolRouter.match_direct_action("Search the web for"))

    def test_normal_conversation_is_not_forced_into_tool(self):
        self.assertIsNone(ToolRouter.match_direct_action("Hi, how are you?"))

    def test_search_discussion_is_not_forced_into_tool(self):
        self.assertIsNone(
            ToolRouter.match_direct_action("Why do search engines rank pages?")
        )

    def test_alias_is_normalized(self):
        self.assertEqual(
            ToolRouter.normalize_action({"action": "check_time"}),
            "get_time",
        )


if __name__ == "__main__":
    unittest.main()
