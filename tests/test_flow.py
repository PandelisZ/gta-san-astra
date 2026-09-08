"""Timing-mode lifecycle checks: inference stays live and failures stop the world."""
import importlib.util
from pathlib import Path

import pytest

from san_astra.control import Controller, ControlError

spec = importlib.util.spec_from_file_location("flow_autodrive", Path(__file__).resolve().parents[1] / "scripts/autodrive.py")
autodrive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autodrive)


class FakeWorld:
    pid = None
    frame_interval_ms = 90

    def __init__(self):
        self.state = "paused"
        self.events = []

    def start_flow(self):
        assert self.state == "paused"
        self.state = "half_speed"
        self.events.append("start")

    def observe(self):
        assert self.state == "half_speed"
        return {"image_path": "/frame.png"}

    def burst(self, segments, fps, continuous):
        assert self.state == "half_speed" and continuous
        self.events.append("normal_action")
        return {"observation": self.observe()}

    def stop_flow(self):
        assert self.state == "half_speed"
        self.state = "paused"
        self.events.append("stop")

    def release(self):
        self.events.append("release")


def run(world, tmp_path, decider):
    return autodrive.run(world, steps=3, goal="Drive", model="gpt-6-astra", directory=tmp_path,
                        mode="flow", frame_stride=60, decision_fn=decider)


def test_inference_runs_at_half_speed_between_normal_actions(tmp_path):
    world = FakeWorld()
    calls = []
    def decide(*args):
        assert world.state == "half_speed"
        assert "world CONTINUES at 50% speed" in args[3]
        calls.append(1)
        return {"buttons": [], "segments": [{"buttons": [], "frames": 60}],
                "rationale": "Clear", "scene": "driving", "stop": len(calls) == 2}, 10
    run(world, tmp_path, decide)
    assert world.events == ["start", "normal_action", "stop", "release"]
    assert world.state == "paused"


def test_inference_failure_pauses_and_releases(tmp_path):
    world = FakeWorld()
    def decide(*args):
        assert world.state == "half_speed"
        raise RuntimeError("inference failed")
    with pytest.raises(RuntimeError, match="inference failed"):
        run(world, tmp_path, decide)
    assert world.events == ["start", "stop", "release"]


def test_failed_stop_still_releases_controls(tmp_path):
    world = FakeWorld()
    def failed_stop():
        raise RuntimeError("pause failed")
    world.stop_flow = failed_stop
    def decide(*args):
        return {"buttons": [], "rationale": "Done", "scene": "driving", "stop": True}, 1
    with pytest.raises(RuntimeError, match="pause failed"):
        run(world, tmp_path, decide)
    assert world.events[-1] == "release"


def test_invalid_speed_config_cannot_unpause(tmp_path):
    ini = tmp_path / "PCSX2.ini"
    ini.write_text("[Hotkeys]\nToggleSlowMotion=Keyboard/Tab\nTogglePause=Keyboard/Space\n"
                   "[Framerate]\nNominalScalar=2\nSlomoScalar=0.5\n")
    controller = Controller(ini_path=ini, run_dir=tmp_path)
    calls = []
    controller.call = lambda *args: calls.append(args)
    with pytest.raises(ControlError, match="NominalScalar=1"):
        controller.start_flow()
    assert calls == []
