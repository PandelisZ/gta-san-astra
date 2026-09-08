#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
sh native/build.sh
sh native/build-daemon.sh
uv sync --extra test
python3 scripts/setup_emulator.py
printf '%s\n' 'Build and isolated profile ready. Quit PCSX2, launch your game with scripts/setup_emulator.py --iso PATH --launch, then run: uv run san-astra doctor' 
