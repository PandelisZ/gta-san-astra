import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location("autodrive", Path(__file__).resolve().parents[1] / "scripts/autodrive.py")
autodrive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autodrive)


def decision(**kwargs):
    return {"buttons": ["cross"], "rationale": "The road ahead is clear.",
            "scene": "driving", "stop": False, **kwargs}


class AutodriveTests(unittest.TestCase):
    def test_invalid_decisions(self):
        for change in ({"frames": True}, {"frames": 121}, {"frames": 0}, {"frames": 1.5},
                       {"buttons": ["cheat"]}, {"buttons": "cross"}, {"stop": "false"},
                       {"scene": "unknown"}, {"rationale": " "}, {"buttons": ["cross", "cross"]},
                       {"buttons": ["steer_left", "steer_right"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                autodrive.validate_decision(decision(**change))

    def test_command_isolated_and_last_two_images(self):
        command = autodrive.build_command("gpt-6-astra", [Path("a"), Path("b"), Path("c")], Path("out"), Path("cwd"))
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ephemeral", command)
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertIn('service_tier="fast"', command)
        self.assertIn('web_search="disabled"', command)
        self.assertIn("shell_tool", command)
        self.assertNotIn(str(Path("a").resolve()), command)
        self.assertEqual(command.count("--image"), 2)

    def test_decide_persists_logs_and_validates(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            def runner(command, **kwargs):
                Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(decision()))
                self.assertIn("Use ONLY", kwargs["input"])
                return subprocess.CompletedProcess(command, 0, "event log", "warning")
            result, latency = autodrive.decide("gpt-6-astra", [Path("frame.png")], [], "Drive", directory, 0, 10, runner)
            self.assertEqual(result, decision())
            self.assertGreaterEqual(latency, 0)
            self.assertEqual((directory / "codex-0000.stdout").read_text(), "event log")

    def test_bounded_loop_and_stop(self):
        controller = Mock()
        controller.observe.return_value = {"image_path": "/frame0.png"}
        controller.step.return_value = {"observation": {"image_path": "/frame1.png"}}
        decider = Mock(side_effect=[(decision(), 12), (decision(stop=True), 14)])
        with tempfile.TemporaryDirectory() as temp:
            result = autodrive.run(controller, steps=20, goal="Drive", model="gpt-6-astra",
                                   directory=Path(temp), decision_fn=decider)
            self.assertEqual(len(result), 2)
            controller.step.assert_called_once_with(buttons=["cross"], frames=5)
            controller.release.assert_called_once()
            self.assertEqual(decider.call_args.args[1], [Path("/frame0.png"), Path("/frame1.png")])

    def test_fixed_stride_and_two_frame_history(self):
        controller = Mock()
        controller.observe.return_value = {"image_path": "/frame0.png"}
        controller.step.side_effect = [{"observation": {"image_path": f"/frame{i}.png"}} for i in range(1, 4)]
        decider = Mock(return_value=(decision(), 1))
        with tempfile.TemporaryDirectory() as temp:
            autodrive.run(controller, steps=3, goal="Drive", model="gpt-6-astra",
                          directory=Path(temp), frame_stride=10, decision_fn=decider)
        self.assertEqual(controller.step.call_count, 3)
        self.assertEqual(controller.step.call_args.kwargs["frames"], 10)
        self.assertEqual(decider.call_args.args[1], [Path("/frame1.png"), Path("/frame2.png")])

    def test_no_stale_decision_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "decision-0000.json").write_text(json.dumps(decision()))
            runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
            with self.assertRaises(ValueError):
                autodrive.decide("gpt-6-astra", [Path("frame.png")], [], "Drive", directory, 0, 10, runner)

    def test_summary_counters_and_stop_status(self):
        controller = Mock()
        controller.observe.return_value = {"image_path": "/frame0.png"}
        controller.step.return_value = {"observation": {"image_path": "/frame1.png"}}
        decider = Mock(side_effect=[(decision(), 10), (decision(stop=True), 20)])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            autodrive.run(controller, steps=3, goal="Drive", model="gpt-6-astra", directory=root,
                          frame_stride=10, decision_fn=decider, scenario_state="/scenario.p2s")
            summary = json.loads((root / "run_summary.json").read_text())
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(summary["reasoning_effort"], "low")
            self.assertEqual(summary["service_tier"], "fast")
            self.assertEqual(summary["action_count"], 1)
            self.assertEqual(summary["decision_count"], 2)
            self.assertEqual(summary["game_frames_requested"], 10)
            self.assertEqual(summary["decision_latency_median_ms"], 15)
            self.assertEqual(summary["scenario_state"], "/scenario.p2s")

    def test_release_failure_does_not_mask_original(self):
        controller = Mock()
        controller.observe.side_effect = ValueError("original capture failure")
        controller.release.side_effect = RuntimeError("release failure")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "original capture failure"):
                autodrive.run(controller, steps=1, goal="Drive", model="gpt-6-astra", directory=root)
            summary = json.loads((root / "run_summary.json").read_text())
            self.assertEqual(summary["status"], "error")
            self.assertEqual(summary["error"], "original capture failure")
            self.assertEqual(summary["release_error"], "release failure")

    def test_malformed_decision_never_actuates(self):
        controller = Mock()
        controller.observe.return_value = {"image_path": "/frame0.png"}
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            autodrive.run(controller, steps=1, goal="Drive", model="gpt-6-astra",
                           directory=Path(temp), decision_fn=Mock(return_value=(decision(frames=-1), 1)))
        controller.step.assert_not_called()
        controller.release.assert_called_once()

    def test_timeout_releases_controls(self):
        controller = Mock()
        controller.observe.return_value = {"image_path": "/frame0.png"}
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(RuntimeError):
            autodrive.run(controller, steps=1, goal="Drive", model="gpt-6-astra",
                           directory=Path(temp), decision_fn=Mock(side_effect=RuntimeError("timeout")))
        controller.step.assert_not_called()
        controller.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
