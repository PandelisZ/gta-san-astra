import json
from mcp.server.fastmcp import FastMCP, Image
from .control import Controller


def frame_result(result):
    observation = result.get("observation", result)
    return [json.dumps(result), Image(path=observation["image_path"])]


def create_server(controller: Controller | None = None):
    controller = controller or Controller()
    server = FastMCP("GTA San Astra", instructions="Control PCSX2 using only rendered screen images. Observe before driving. Infer road, obstacles and vehicle motion visually; no game memory or telemetry is available. Actions hold buttons for 50–2000 ms then release and capture a frame. Start with short 100–250 ms actions. Prefer step when emulator is paused: advances requested frames and keeps paused during inference. Regular action uses real time and game time continues between actions. Button cross accelerates, square brakes/reverses, triangle enters/exits vehicle, R1 handbrakes. Never claim a collision or speed measurement without visual evidence.")

    @server.tool()
    def observe():
        """Return a fresh game screenshot and capture metadata. Screen pixels are the only game observation."""
        return frame_result(controller.observe())

    @server.tool()
    def action(buttons: list[str] | None = None, duration_ms: int = 150, throttle: bool = False, brake: bool = False, steer: str = "center", handbrake: bool = False):
        """Hold PS2 buttons for 50–2000ms, release, then return a fresh screenshot. steer: left/center/right. Buttons: cross,square,triangle,circle,left,right,up,down,l1,r1,l2,r2,start,select,steer_left,steer_right,move_forward,move_backward,l_up,l_down,l3,r3,look_up,look_down,look_left,look_right. Empty action coasts for the duration."""
        return frame_result(controller.action(buttons, duration_ms, throttle, brake, steer, handbrake))

    @server.tool()
    def step(buttons: list[str] | None = None, frames: int | None = None, throttle: bool = False, brake: bool = False, steer: str = "center", handbrake: bool = False):
        """Preferred driving loop: hold controls and advance 1–120 paused frames, release, return screenshot. Requires prepared PCSX2 profile with FrameAdvance=N and paused emulation. Game remains paused while you reason. Omit frames to use configured observation stride (default 60). Frames count VSync requests, not a guaranteed FPS. Steering is digital left/center/right."""
        return frame_result(controller.step(buttons, frames, throttle, brake, steer, handbrake))

    @server.tool()
    def release():
        """Emergency release of all injected keys."""
        return controller.release()

    @server.tool()
    def doctor():
        """Check bridge, macOS permissions, emulator windows and configured keyboard mappings."""
        return controller.doctor()

    return server
