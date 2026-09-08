import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from san_astra.control import Controller, ControlError


spec = importlib.util.spec_from_file_location("scenario", Path(__file__).resolve().parents[1] / "scripts/scenario.py")
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setenv("SAN_ASTRA_LOCK", str(tmp_path / "lock"))
    profile = tmp_path / "pcsx2"
    ini = profile / "inis/PCSX2.ini"
    ini.parent.mkdir(parents=True)
    states = profile / "sstates"
    states.mkdir()
    ini.write_text(f"[Folders]\nSavestates = {states}\n[Hotkeys]\nSaveStateToSlot = Keyboard/F1\n")
    monkeypatch.setenv("SAN_ASTRA_PCSX2_INI", str(ini))
    controller = Controller(run_dir=tmp_path / "runs")
    calls = []
    def call(*args):
        calls.append(args)
        if args[0] == "input":
            (states / "GAME (ABCD).00.p2s").write_bytes(b"opaque savestate bytes")
        elif args[0] == "capture":
            Image.new("RGB", (20, 20), "blue").save(args[args.index("--output") + 1])
        return {"ok": True}
    controller.call = call
    return controller, tmp_path / "scenarios", states, calls


def test_capture_finds_save_and_copies_opaque_artifacts(scene):
    controller, scenarios, states, calls = scene
    result = scenario.capture(controller, scenarios=scenarios)
    target = scenarios / "stationary-car"
    assert (target / "state.p2s").read_bytes() == b"opaque savestate bytes"
    assert (target / "frame.png").is_file()
    assert result["manifest"]["state_sha256"] == scenario.digest(target / "state.p2s")
    assert [c[0] for c in calls] == ["input", "capture"]
    assert calls[0][2] == "f1"
    assert "opaque reset artifact" in result["manifest"]["pixel_only_invariant"]


def test_existing_scenario_refused_before_save(scene):
    controller, scenarios, states, calls = scene
    (scenarios / "stationary-car").mkdir(parents=True)
    with pytest.raises(ValueError, match="already exists"):
        scenario.capture(controller, scenarios=scenarios)
    assert not calls


def test_wrong_hotkey_refused_before_save(scene):
    controller, scenarios, states, calls = scene
    controller.config_path.write_text("[Hotkeys]\nSaveStateToSlot = Keyboard/F5\n")
    with pytest.raises(ControlError, match="Keyboard/F1"):
        scenario.capture(controller, scenarios=scenarios)
    assert not calls


def test_save_outside_profile_refused(scene, tmp_path):
    controller, scenarios, states, calls = scene
    controller.config_path.write_text(f"[Hotkeys]\nSaveStateToSlot = Keyboard/F1\n[Folders]\nSavestates = {tmp_path / 'elsewhere'}\n")
    with pytest.raises(ControlError, match="outside"):
        scenario.capture(controller, scenarios=scenarios)
    assert not calls


@pytest.mark.parametrize("name", ["../escape", "/absolute", ".", "has/slash", ""])
def test_invalid_scenario_names(tmp_path, name):
    with pytest.raises(ValueError):
        scenario.destination(tmp_path, name)


def test_unchanged_save_times_out(tmp_path):
    state = tmp_path / "existing.p2s"
    state.write_bytes(b"old")
    with pytest.raises(ControlError, match="No new or updated"):
        scenario.wait_for_save(tmp_path, scenario.state_files(tmp_path), timeout=0.01)


def test_multiple_new_saves_refused(tmp_path):
    (tmp_path / "one.p2s").write_bytes(b"one")
    (tmp_path / "two.p2s").write_bytes(b"two")
    with pytest.raises(ControlError, match="Multiple"):
        scenario.wait_for_save(tmp_path, {}, timeout=1)


def saved_scenario(tmp_path):
    target = tmp_path / "scenarios/stationary-car"
    target.mkdir(parents=True)
    (target / "state.p2s").write_bytes(b"opaque")
    (target / "manifest.json").write_text(json.dumps({"state_sha256": scenario.digest(target / "state.p2s"), "game_filename": "game.iso"}))
    iso = tmp_path / "game.iso"
    iso.write_bytes(b"game")
    return target, iso


def test_launch_refuses_running_emulator(tmp_path, monkeypatch):
    target, iso = saved_scenario(tmp_path)
    monkeypatch.setattr(scenario.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    with pytest.raises(ControlError, match="PCSX2 is running"):
        scenario.launch("stationary-car", iso, target.parent)


def test_launch_passes_immutable_statefile_without_changing_slot(tmp_path, monkeypatch):
    target, iso = saved_scenario(tmp_path)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1 if args[0] == "pgrep" else 0, stdout="launched", stderr="")
    monkeypatch.setattr(scenario.subprocess, "run", run)
    scenario.launch("stationary-car", iso, target.parent)
    assert calls[1][calls[1].index("--statefile") + 1] == str(target / "state.p2s")
    assert "--launch" in calls[1]


def test_launch_refuses_modified_state(tmp_path, monkeypatch):
    target, iso = saved_scenario(tmp_path)
    (target / "state.p2s").write_bytes(b"modified")
    with pytest.raises(ControlError, match="integrity"):
        scenario.launch("stationary-car", iso, target.parent)


def test_failed_replacement_preserves_previous_scenario(scene, monkeypatch):
    controller, scenarios, states, calls = scene
    target = scenarios / "stationary-car"
    target.mkdir(parents=True)
    (target / "state.p2s").write_bytes(b"previous intact state")
    normal_copy = scenario.shutil.copy2
    def changing_copy(source, destination):
        result = normal_copy(source, destination)
        if Path(source).suffix == ".p2s":
            Path(source).write_bytes(b"changed during snapshot copy")
        return result
    monkeypatch.setattr(scenario.shutil, "copy2", changing_copy)
    with pytest.raises(ControlError, match="changed while copying"):
        scenario.capture(controller, scenarios=scenarios, replace=True)
    assert (target / "state.p2s").read_bytes() == b"previous intact state"
    assert list(scenarios.iterdir()) == [target]


def test_launch_wrong_game_filename_fails_before_process_check(tmp_path, monkeypatch):
    target, iso = saved_scenario(tmp_path)
    wrong_iso = tmp_path / "other-game.iso"
    wrong_iso.write_bytes(b"other game")
    def forbidden(*args, **kwargs):
        pytest.fail("Should not launch a mismatched game")
    monkeypatch.setattr(scenario.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="Game filename differs"):
        scenario.launch("stationary-car", wrong_iso, target.parent)
