import sys
import unittest
from unittest.mock import Mock

from san_astra.control import ControlError
from san_astra.daemon import DaemonClient, DaemonController


ECHO = '''import sys,json
for line in sys.stdin:
 r=json.loads(line)
 print(json.dumps({"id":r["id"],"ok":r["op"]!="fail","echo":r,"error":"rejected"}),flush=True)
'''


class DaemonTests(unittest.TestCase):
    def test_persistent_process_request_ids_and_recovery(self):
        with DaemonClient([sys.executable, "-u", "-c", ECHO]) as client:
            first = client.request("status")
            process = client.process
            with self.assertRaisesRegex(ControlError, "rejected"):
                client.request("fail")
            last = client.request("status")
            self.assertIs(client.process, process)
            self.assertEqual(first["id"], 1)
            self.assertEqual(last["id"], 3)
        self.assertIsNotNone(process.returncode)

    def test_timeout_closes_transport(self):
        with DaemonClient([sys.executable, "-u", "-c", "import sys,time;sys.stdin.readline();time.sleep(10)"], timeout=0.03) as client:
            with self.assertRaisesRegex(ControlError, "timed out"):
                client.request("status")
            self.assertIsNotNone(client.process.returncode)
            with self.assertRaisesRegex(ControlError, "closed"):
                client.request("status")

    def test_wrong_id_fails_closed(self):
        command = [sys.executable, "-u", "-c", 'import sys;sys.stdin.readline();print(\'{"id":99,"ok":true}\',flush=True)']
        with DaemonClient(command) as client:
            with self.assertRaisesRegex(ControlError, "ID"):
                client.request("status")

    def test_controller_argument_mapping(self):
        client = Mock()
        controller = DaemonController(daemon_client=client)
        controller.call("step", "--keys", "k,a", "--frames", "5", "--frame-key", "n", "--frame-interval-ms", "35")
        client.request.assert_called_once_with("step", keys=["k", "a"], frames=5, frame_key="n", frame_interval_ms=35)
        client.reset_mock()
        controller.call("input", "--keys", "", "--duration-ms", "150", "--focus")
        client.request.assert_called_once_with("input", keys=[], duration_ms=150, focus=True)


if __name__ == "__main__":
    unittest.main()
