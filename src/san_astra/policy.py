"""Persistent, authenticated Codex app-server vision policy; no emulator access."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import tempfile
import time
import tomllib


DISABLED = ("shell_tool", "unified_exec", "apps", "plugins", "remote_plugin", "browser_use",
            "browser_use_external", "computer_use", "in_app_browser", "image_generation",
            "multi_agent", "multi_agent_v2", "memories", "hooks", "skill_search", "view_image",
            "code_mode_host", "code_mode", "workspace_dependencies", "goals", "tool_suggest",
            "shell_snapshot", "unbounded_connection_retries")


class PolicyError(RuntimeError):
    pass


class CodexPolicy:
    def __init__(self, model="gpt-6-astra", directory: Path = Path("runs/policy"), timeout=45,
                 effort="low", service_tier="fast", context_turns=4):
        self.model, self.timeout, self.effort, self.service_tier = model, timeout, effort, service_tier
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._workspace = tempfile.TemporaryDirectory(prefix="san-astra-policy-")
        self.cwd = Path(self._workspace.name)
        self.messages = queue.Queue()
        self.pending = []
        self.request_id = 0
        self.index = 0
        self.context_turns = max(1, int(context_turns))
        roots = [Path.home() / ".codex/skills", Path.home() / ".agents/skills", Path.home() / ".codex/plugins/cache"]
        self.disabled_skills = [{"path": path, "enabled": False} for path in sorted({str(p.resolve()) for root in roots if root.exists() for p in root.rglob("SKILL.md")})]
        self.thread_id = None
        self.last_turn_id = None
        executable = os.environ.get("SAN_ASTRA_CODEX", "/Applications/ChatGPT.app/Contents/Resources/codex")
        command = [executable, "app-server", "--stdio", "--enable", "skip_host_skill_discovery"]
        for name in DISABLED:
            command.extend(["--disable", name])
        config = {"web_search": '"disabled"', "project_doc_max_bytes": "0",
                  "model_provider": '"san-astra-http"',
                  "model_providers.san-astra-http.name": '"OpenAI HTTPS"',
                  "model_providers.san-astra-http.base_url": '"https://chatgpt.com/backend-api/codex"',
                  "model_providers.san-astra-http.wire_api": '"responses"',
                  "model_providers.san-astra-http.requires_openai_auth": "true",
                  "model_providers.san-astra-http.supports_websockets": "false",
                  "model_providers.san-astra-http.request_max_retries": "0",
                  "model_providers.san-astra-http.stream_max_retries": "0"}
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        catalog = codex_home / "models_cache.json"
        if catalog.is_file():
            config["model_catalog_json"] = json.dumps(str(catalog))
        config_file = codex_home / "config.toml"
        if config_file.exists():
            for name in tomllib.loads(config_file.read_text()).get("mcp_servers", {}):
                config[f"mcp_servers.{name}.enabled"] = "false"
        for name, value in config.items():
            command.extend(["-c", f"{name}={value}"])
        self.stderr = (self.directory / "app-server.stderr").open("a")
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, text=True, bufsize=1, cwd=self.cwd)
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            self._request("initialize", {"clientInfo": {"name": "san_astra_policy", "version": "0.1.0"},
                                         "capabilities": {"experimentalApi": True}})
            self._send({"method": "initialized"})
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            self.messages.put({"_eof": True})

    def _send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _next(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PolicyError("Codex policy request timed out")
        try:
            message = self.messages.get(timeout=remaining)
        except queue.Empty as exc:
            raise PolicyError("Codex policy request timed out") from exc
        if message.get("_eof"):
            raise PolicyError(f"Codex app-server exited; inspect {self.directory / 'app-server.stderr'}")
        if "method" in message and "id" in message:
            self._send({"id": message["id"], "error": {"code": -32601, "message": "Tools and approvals are disabled for the visual policy"}})
            raise PolicyError(f"Visual policy requested forbidden client operation: {message['method']}")
        return message

    def _request(self, method, params):
        self.request_id += 1
        request_id = self.request_id
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            message = self._next(deadline)
            if message.get("id") == request_id:
                if "error" in message:
                    raise PolicyError(f"{method}: {message['error']}")
                return message.get("result", {})
            self.pending.append(message)

    def decide(self, images: list[Path], prompt: str, output_schema: dict):
        if not images or any(not Path(image).is_file() for image in images[-2:]):
            raise ValueError("Policy requires one or two existing game screenshots")
        started = time.monotonic()
        if self.last_turn_id is not None:
            deadline = time.monotonic() + self.timeout
            while True:
                message = self.pending.pop(0) if self.pending else self._next(deadline)
                if message.get("method") == "thread/tokenUsage/updated":
                    (self.directory / f"policy-{self.index - 1:04d}.usage.json").write_text(json.dumps(message["params"]["tokenUsage"], indent=2) + "\n")
                if message.get("method") == "turn/completed" and message.get("params", {}).get("turn", {}).get("id") == self.last_turn_id:
                    break
            self.last_turn_id = None
        # Reuse a short policy context for prefix caching, then reset it.
        if self.thread_id is None or self.index % self.context_turns == 0:
            thread = self._request("thread/start", {
                "model": self.model, "cwd": str(self.cwd), "ephemeral": True,
                "approvalPolicy": "never", "sandbox": "read-only", "environments": [],
                "serviceTier": self.service_tier,
                "baseInstructions": "You are a screenshot-only game driving policy. Use only attached images and supplied previous actions. Do not call any tools. Return only the requested JSON object with a very brief visible-scene rationale.",
                "developerInstructions": "No filesystem, network, shell, browser, memory, or telemetry access. Never execute tools.",
                "dynamicTools": [], "selectedCapabilityRoots": [],
                "config": {"project_doc_max_bytes": 0, "web_search": "disabled", "skills": {"config": self.disabled_skills}}})
            self.thread_id = thread["thread"]["id"]
        thread_id = self.thread_id
        self.pending.clear()
        turn = self._request("turn/start", {"threadId": thread_id,
            "input": [{"type": "text", "text": prompt}] + [{"type": "localImage", "path": str(Path(image).resolve())} for image in images[-2:]],
            "effort": self.effort, "summary": "none", "serviceTier": self.service_tier,
            "outputSchema": output_schema, "environments": []})
        turn_id = turn["turn"]["id"]
        self.last_turn_id = turn_id
        deadline = time.monotonic() + self.timeout
        chunks, final, events = [], None, []
        try:
            while True:
                message = self.pending.pop(0) if self.pending else self._next(deadline)
                params = message.get("params", {})
                if params.get("threadId") not in (None, thread_id):
                    continue
                events.append(message)
                method = message.get("method")
                if method == "item/agentMessage/delta":
                    chunks.append(params.get("delta", ""))
                if method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                    final = params["item"].get("text")
                    if params["item"].get("phase") == "final_answer" and final:
                        break
                if method == "turn/completed":
                    completed = params.get("turn", {})
                    if completed.get("status") != "completed":
                        raise PolicyError(f"Codex turn failed: {completed.get('error') or completed.get('status')}")
                    self.last_turn_id = None
                    break
            result = json.loads(final if final is not None else "".join(chunks))
            elapsed = round((time.monotonic() - started) * 1000, 2)
            (self.directory / f"policy-{self.index:04d}.json").write_text(json.dumps({"decision": result, "latency_ms": elapsed,
                "model": self.model, "effort": self.effort, "service_tier": self.service_tier,
                "thread_id": thread_id, "turn_id": turn_id}, indent=2) + "\n")
            return result, elapsed
        finally:
            (self.directory / f"policy-{self.index:04d}.events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
            self.index += 1

    def close(self):
        if getattr(self, "process", None) and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if getattr(self, "stderr", None):
            self.stderr.close()
        if getattr(self, "_workspace", None):
            self._workspace.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
