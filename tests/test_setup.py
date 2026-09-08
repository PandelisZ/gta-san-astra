import configparser
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("setup_emulator", Path(__file__).resolve().parents[1] / "scripts/setup_emulator.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def config(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(path)
    return parser


@pytest.fixture
def profile(tmp_path):
    source = tmp_path / "source"
    (source / "inis").mkdir(parents=True)
    (source / "bios").mkdir()
    (source / "bios/test.bin").write_bytes(bytes(1024 * 1024))
    (source / "inis/PCSX2.ini").write_text("[Filenames]\nBIOS=test.bin\n[Folders]\nBios=bios\n")
    return source, tmp_path / "experiment/PCSX2"


def test_normalizes_bindings_and_isolates_absolute_writable_paths(profile):
    source, target = profile
    original = source / "inis/PCSX2.ini"
    original.write_text(original.read_text() + f"MemoryCards={source}/memcards\nSavestates={source}/sstates\n[MemoryCards]\nSlot1_Filename={source}/memcards/original.ps2\n[Pad1]\nCross=SDL-0/A\n[Hotkeys]\nToggleTurbo=Keyboard/K\n")
    source_bytes = original.read_bytes()
    result = config(setup.prepare(source, target))
    assert original.read_bytes() == source_bytes
    assert result["Pad1"]["Cross"] == "Keyboard/K"
    assert result["Hotkeys"]["ToggleTurbo"] == ""
    assert result["Hotkeys"]["ToggleSlowMotion"] == "Keyboard/Tab"
    assert result["Framerate"]["NominalScalar"] == "1"
    assert result["Framerate"]["SlomoScalar"] == "0.5"
    assert result["Hotkeys"]["FrameAdvance"] == "Keyboard/N"
    assert result["MemoryCards"]["Slot1_Filename"] == "original.ps2"
    for name in setup.WRITABLE_FOLDERS:
        assert Path(result["Folders"][name]).is_relative_to(target)
    assert not (source / "memcards").exists()


def test_reconciles_existing_config_and_preserves_isolated_files(profile):
    source, target = profile
    ini = setup.prepare(source, target)
    card = target / "memcards/user.ps2"
    card.write_bytes(b"precious isolated save")
    saved = config(ini)
    saved["UI"]["StartPaused"] = "false"
    saved["Hotkeys"]["FrameAdvance"] = "Keyboard/P"
    saved["Folders"]["Savestates"] = str(target / "custom-states")
    saved["OtherSetting"] = {"Value": "preserve me"}
    with ini.open("w") as stream:
        saved.write(stream)
    result = config(setup.prepare(source, target))
    assert result["UI"]["StartPaused"] == "true"
    assert result["Hotkeys"]["FrameAdvance"] == "Keyboard/N"
    assert result["OtherSetting"]["Value"] == "preserve me"
    assert result["Folders"]["Savestates"] == str(target / "custom-states")
    assert card.read_bytes() == b"precious isolated save"


@pytest.mark.parametrize("absolute", [False, True])
def test_resolves_custom_bios_folder(profile, absolute):
    source, target = profile
    custom = source / "custom-bios"
    custom.mkdir()
    (source / "bios/test.bin").rename(custom / "test.bin")
    folder = str(custom) if absolute else "custom-bios"
    (source / "inis/PCSX2.ini").write_text(f"[Filenames]\nBIOS=test.bin\n[Folders]\nBios={folder}\n")
    result = config(setup.prepare(source, target))
    assert result["Folders"]["Bios"] == str(target / "bios")
    assert (target / "bios/test.bin").read_bytes() == (custom / "test.bin").read_bytes()


def test_missing_bios_does_not_mutate_existing_profile(profile):
    source, target = profile
    ini = setup.prepare(source, target)
    before = ini.read_bytes()
    (source / "bios/test.bin").unlink()
    (target / "bios/test.bin").unlink()
    with pytest.raises(ValueError, match="BIOS"):
        setup.prepare(source, target)
    assert ini.read_bytes() == before


def test_refuses_source_target_alias(profile):
    source, _ = profile
    with pytest.raises(ValueError, match="differ"):
        setup.prepare(source, source)


def test_refuses_symlink_writable_directory_outside_profile(profile, tmp_path):
    source, target = profile
    target.mkdir(parents=True)
    (target / "memcards").symlink_to(source)
    with pytest.raises(ValueError, match="outside profile"):
        setup.prepare(source, target)
    assert not (target / "inis/PCSX2.ini").exists()


def test_refuses_symlink_config_directory_outside_profile(profile):
    source, target = profile
    target.mkdir(parents=True)
    (target / "inis").symlink_to(source / "inis")
    before = (source / "inis/PCSX2.ini").read_bytes()
    with pytest.raises(ValueError, match="outside profile"):
        setup.prepare(source, target)
    assert (source / "inis/PCSX2.ini").read_bytes() == before


def test_bios_sidecars_are_copied_once_and_isolated_changes_preserved(profile):
    source, target = profile
    (source / "bios/test.NVM").write_bytes(b"original nvm")
    (source / "bios/test.MEC").write_bytes(b"original mec")
    (source / "bios/unrelated.NVM").write_bytes(b"unrelated")
    ini = setup.prepare(source, target)
    assert (target / "bios/test.NVM").read_bytes() == b"original nvm"
    assert (target / "bios/test.MEC").read_bytes() == b"original mec"
    assert not (target / "bios/unrelated.NVM").exists()
    (target / "bios/test.NVM").write_bytes(b"isolated prefs")
    (source / "bios/test.NVM").write_bytes(b"changed original")
    (source / "bios/test.bin").unlink()
    setup.prepare(source, target)
    assert (target / "bios/test.NVM").read_bytes() == b"isolated prefs"
    assert (source / "bios/test.NVM").read_bytes() == b"changed original"
    assert config(ini)["Folders"]["Bios"] == str(target / "bios")


def test_existing_profile_without_source_reuses_own_bios(profile):
    source, target = profile
    setup.prepare(source, target)
    (source / "inis/PCSX2.ini").unlink()
    # Source now comes from the isolated configuration; copying to itself must be skipped.
    setup.prepare(source, target)
    assert (target / "bios/test.bin").stat().st_size == 1024 * 1024
