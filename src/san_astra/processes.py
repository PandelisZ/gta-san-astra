"""Read-only PCSX2 process/profile matching for isolated multi-instance launches."""
from pathlib import Path
import re
import subprocess


def pcsx2_pids() -> list[int]:
    result = subprocess.run(["pgrep", "-x", "PCSX2"], text=True, capture_output=True)
    return [int(value) for value in result.stdout.split() if value.isdigit()]


def profile_pids(profile: Path) -> list[int]:
    profile = Path(profile).expanduser().resolve()
    matches = []
    pattern = re.compile(r"(?:^|\s)-datapath\s+" + re.escape(str(profile.parent)) + r"(?=\s|$)")
    for pid in pcsx2_pids():
        result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], text=True, capture_output=True)
        if pattern.search(result.stdout):
            matches.append(pid)
    return matches


def verify_profile_pid(pid: int, profile: Path):
    if pid not in profile_pids(profile):
        raise ValueError(f"PCSX2 PID {pid} is not running with profile {Path(profile).resolve()}")
