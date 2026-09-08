import argparse
import json
import sys
from pathlib import Path
from .control import Controller, ControlError


def main():
    parser = argparse.ArgumentParser(description="GTA San Astra: frame-only PCSX2 visual driving")
    parser.add_argument("--bridge", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--window-id", type=int)
    parser.add_argument("--crop-top", type=int, help="Remove top window pixels; default 32 for macOS titlebar, use 0 for fullscreen")
    parser.add_argument("--frame-stride", type=int, help="Default observation interval in emulated VSync requests (1–120); default 5")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "observe", "release", "mcp"):
        subs.add_parser(name)
    action = subs.add_parser("action")
    step = subs.add_parser("step", parents=[], help="Advance paused game frames, then observe")
    step.add_argument("--frames", type=int, help="Override configured frame stride")
    step.add_argument("--buttons", default="")
    step.add_argument("--throttle", action="store_true")
    step.add_argument("--brake", action="store_true")
    step.add_argument("--handbrake", action="store_true")
    step.add_argument("--steer", choices=["left", "center", "right"], default="center")
    action.add_argument("--buttons", default="", help="Comma-separated PS2 button names")
    action.add_argument("--duration-ms", type=int, default=150)
    action.add_argument("--throttle", action="store_true")
    action.add_argument("--brake", action="store_true")
    action.add_argument("--handbrake", action="store_true")
    action.add_argument("--steer", choices=["left", "center", "right"], default="center")
    args = parser.parse_args()
    try:
        controller = Controller(args.bridge, args.run_dir, args.window_id, args.frame_stride, args.crop_top)
        if args.command == "mcp":
            from .server import create_server
            create_server(controller).run(transport="stdio")
            return
        if args.command == "step":
            result = controller.step([x.strip().lower() for x in args.buttons.split(",") if x.strip()], args.frames, args.throttle, args.brake, args.steer, args.handbrake)
        elif args.command == "action":
            result = controller.action([x.strip().lower() for x in args.buttons.split(",") if x.strip()], args.duration_ms, args.throttle, args.brake, args.steer, args.handbrake)
        else:
            result = getattr(controller, args.command)()
        print(json.dumps(result, indent=2))
    except (ControlError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

