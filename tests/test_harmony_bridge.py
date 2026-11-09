"""#898：窗口桥只转发，鸿蒙状态与构造逻辑不落在 Api 上。"""
import tempfile
import unittest
from pathlib import Path

from fixtures import FakeRunner
from gui import app, harmony_bridge


class Service:
    def __init__(self):
        self.calls = []

    def command(self, action, serial="", mode="clean", segments=None):
        self.calls.append((action, serial, mode, segments))
        return {"action": action}


class ApiSurfaceTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.api = app.Api(Path(temp.name), runner=FakeRunner())

    def test_api_does_not_hold_harmony_state(self):
        self.assertFalse(hasattr(self.api, "harmony_service"))
        self.assertFalse(hasattr(self.api, "harmony_lock"))
        self.assertIsInstance(self.api.harmony_bridge, harmony_bridge.HarmonyBridge)

    def test_bridge_forwards_the_bridge_table(self):
        service = Service()
        self.api.harmony_bridge.service = service
        self.assertEqual(self.api.harmony("poll"), {"action": "poll"})
        self.assertEqual(service.calls, [("poll", "", "clean", None)])


class BridgeTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.claim = lambda name: ""
        self.release = lambda: None

    def test_builds_the_service_once(self):
        built = []

        def factory(root, claim, release):
            built.append((root, claim, release))
            return Service()

        bridge = harmony_bridge.HarmonyBridge(self.root, self.claim, self.release, True, factory=factory)
        bridge.command("poll")
        bridge.command("poll")
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0][0], self.root)

    def test_close_is_a_noop_without_a_service(self):
        bridge = harmony_bridge.HarmonyBridge(self.root, self.claim, self.release, True, factory=lambda *a: Service())
        self.assertTrue(bridge.close_if_idle())
        closed = []
        bridge.close_when_done(lambda: closed.append(True))
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
