import json
from pathlib import Path
import pytest
from PIL import Image
from san_astra.control import Controller, ControlError, read_mapping
from san_astra.server import create_server


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("SAN_ASTRA_LOCK", str(tmp_path / "control.lock"))
    c = Controller(run_dir=tmp_path / "runs")
    c.config_path = tmp_path / "profile.ini"
    c.config_path.write_text("[Hotkeys]\nFrameAdvance = Keyboard/N\n")
    c.mapping.update(cross="K", steer_left="A")
    c.calls = []
    def call(*args):
        c.calls.append(args)
        if args[0] == "capture":
            Image.new("RGB", (16, 12), "blue").save(args[args.index("--output") + 1])
        return {"ok": True}
    c.call = call
    return c


def test_action_releases_then_observes_and_records(controller):
    result = controller.action(throttle=True, steer="left", duration_ms=250)
    assert controller.calls[0] == ("input", "--keys", "k,a", "--duration-ms", "250", "--focus")
    assert [c[0] for c in controller.calls] == ["input", "capture"]
    assert Path(result["observation"]["image_path"]).is_file()
    events = [json.loads(line) for line in next(controller.run_dir.glob("*/events.jsonl")).read_text().splitlines()]
    assert [e["type"] for e in events] == ["action", "observation"]


@pytest.mark.parametrize("duration", [0, 49, 2001, -1, True, 100.5])
def test_duration_bounds_before_input(controller, duration):
    with pytest.raises(ValueError):
        controller.action(duration_ms=duration)
    assert not controller.calls


@pytest.mark.parametrize("frames", [0, 121, True, 1.5])
def test_frame_bounds_before_input(controller, frames):
    with pytest.raises(ValueError):
        controller.step(frames=frames)
    assert not controller.calls


def test_step_mapping_and_contract(controller):
    result = controller.step(frames=12, throttle=True)
    assert controller.calls[0] == ("step", "--keys", "k", "--frames", "12", "--frame-key", "n", "--frame-interval-ms", "35")
    assert result["action"]["frames"] == 12
    assert "duration_ms" not in result["action"]


def test_release_on_input_failure(controller):
    normal = controller.call
    def failing(*args):
        if args[0] == "input":
            controller.calls.append(args)
            raise ControlError("test input failed")
        return normal(*args)
    controller.call = failing
    with pytest.raises(ControlError, match="test input failed"):
        controller.action(throttle=True)
    assert [c[0] for c in controller.calls] == ["input", "release"]
    assert controller.calls[-1] == ("release", "--keys", "k")


def test_action_lock_prevents_concurrent_input(controller):
    with controller.lock():
        with pytest.raises(ControlError, match="Another San Astra"):
            controller.action(throttle=True)
    assert not controller.calls


def test_ini_mapping(tmp_path):
    ini = tmp_path / "PCSX2.ini"
    ini.write_text("[Pad1]\nCross = SDL-0/A & Keyboard/X\nLLeft = Keyboard/F\n")
    mapping, source = read_mapping(ini)
    assert mapping["cross"] == "X"
    assert mapping["steer_left"] == "F"
    assert source == str(ini)


def test_unknown_buttons_fail_before_input(controller):
    with pytest.raises(ValueError, match="Unknown buttons"):
        controller.action(buttons=["warp"])
    assert not controller.calls


def test_mcp_returns_actual_image(controller):
    import asyncio
    server = create_server(controller)
    result = asyncio.run(server.call_tool("observe", {}))
    assert result[0].type == "text"
    assert result[1].type == "image"
    assert result[1].mimeType == "image/png"
    import base64
    assert base64.b64decode(result[1].data).startswith(b"\x89PNG")


def test_configured_stride_used_when_frames_omitted(controller):
    controller.default_frame_stride = 10
    result = controller.step()
    assert result["action"]["frames"] == 10
    assert controller.step(frames=1)["action"]["frames"] == 1


def test_neutral_action_releases_waits_and_captures(controller, monkeypatch):
    waits = []
    monkeypatch.setattr("san_astra.control.time.sleep", waits.append)
    result = controller.action(duration_ms=150)
    assert waits == [0.15]
    assert [call[0] for call in controller.calls] == ["release", "capture"]
    assert result["action"]["native"]["neutral"]


@pytest.mark.parametrize("buttons", ["cross", True, [True], [3], {}])
def test_malformed_buttons_fail_before_input(controller, buttons):
    with pytest.raises(ValueError, match="list of button name strings"):
        controller.action(buttons=buttons)
    assert not controller.calls


@pytest.mark.parametrize("kwargs", [{"throttle": 1}, {"brake": "false"}, {"handbrake": None}])
def test_boolean_controls_require_booleans(controller, kwargs):
    with pytest.raises(ValueError, match="must be booleans"):
        controller.action(**kwargs)
    assert not controller.calls


def test_movement_aliases_read_actual_mapping(tmp_path):
    ini = tmp_path / "PCSX2.ini"
    ini.write_text("[Pad1]\nLUp = Keyboard/U\nLDown = Keyboard/O\nRLeft = Keyboard/Z\nL3 = Keyboard/5\n")
    mapping, _ = read_mapping(ini)
    assert mapping["move_forward"] == mapping["l_up"] == "U"
    assert mapping["move_backward"] == mapping["l_down"] == "O"
    assert mapping["look_left"] == "Z"
    assert mapping["l3"] == "5"


def test_doctor_warns_about_wrong_frame_binding(controller, tmp_path):
    controller.config_path = tmp_path / "profile.ini"
    controller.config_path.write_text("[Hotkeys]\nFrameAdvance = Keyboard/F\n")
    assert controller.doctor()["frame_advance_configured"] is False
    assert controller.doctor()["warnings"]
    controller.config_path.write_text("[Hotkeys]\nFrameAdvance = Keyboard/N\n")
    assert controller.doctor()["frame_advance_configured"] is True
    assert not controller.doctor()["warnings"]


def test_config_override_precedes_isolated_profile(tmp_path, monkeypatch):
    from san_astra.control import config_path
    target = tmp_path / "custom.ini"
    monkeypatch.setenv("SAN_ASTRA_PCSX2_INI", str(target))
    assert config_path() == target


def test_capture_passes_titlebar_crop(controller):
    controller.observe()
    assert controller.calls[0][-2:] == ("--crop-top", "32")
    controller.crop_top = 0
    controller.observe()
    assert controller.calls[-1][-2:] == ("--crop-top", "0")


def test_step_refuses_wrong_frame_binding(controller):
    controller.config_path.write_text("[Hotkeys]\nFrameAdvance = Keyboard/F\n")
    with pytest.raises(ControlError, match="FrameAdvance = Keyboard/N"):
        controller.step(throttle=True)
    assert not controller.calls


def test_crop_environment_override(monkeypatch):
    monkeypatch.setenv("SAN_ASTRA_CROP_TOP", "0")
    assert Controller().crop_top == 0
    assert Controller(crop_top=12).crop_top == 12


@pytest.mark.parametrize("crop", [-1, 4097, True, 1.5])
def test_invalid_crop_rejected(crop):
    with pytest.raises(ValueError, match="crop_top"):
        Controller(crop_top=crop)


def test_missing_keyboard_binding_refuses_input(controller, tmp_path):
    ini = tmp_path / "pad.ini"
    ini.write_text("[Pad1]\nCross = SDL-0/A\n")
    controller.mapping, controller.mapping_source = read_mapping(ini)
    with pytest.raises(ControlError, match="No keyboard binding"):
        controller.action(throttle=True)
    assert not controller.calls


def test_failure_releases_remapped_key_only(controller):
    controller.mapping["cross"] = "Z"
    normal = controller.call
    def failing(*args):
        if args[0] == "input":
            controller.calls.append(args)
            raise ControlError("bridge crashed")
        return normal(*args)
    controller.call = failing
    with pytest.raises(ControlError, match="bridge crashed"):
        controller.action(throttle=True)
    assert controller.calls[-1] == ("release", "--keys", "z")
