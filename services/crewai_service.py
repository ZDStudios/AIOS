#!/usr/bin/env python3
"""
CrewAI service for The AI OS.

Wraps the bundled CrewAI framework in a tiny HTTP endpoint so the AIOS Hub and
dashboard can talk to it, and gives the crew a tool to reach the other agents
through the hub (the interconnect).

Run by `aios start crewai` inside CrewAI's uv environment:
    uv run --project crewAI-main/crewAI-main python services/crewai_service.py

Env: AIOS_CREWAI_PORT, AIOS_DEFAULT_MODEL, AIOS_LLM_PROVIDER, AIOS_LLM_API_KEY,
     OPENROUTER_API_KEY/OPENAI_API_KEY/ANTHROPIC_API_KEY, AIOS_HUB_URL
"""
from __future__ import annotations

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("AIOS_CREWAI_PORT", "4788"))
HUB = os.environ.get("AIOS_HUB_URL", "http://127.0.0.1:8787").rstrip("/")


def litellm_model() -> str:
    """Map AIOS_DEFAULT_MODEL + provider to a litellm model string CrewAI understands."""
    model = os.environ.get("AIOS_DEFAULT_MODEL", "anthropic/claude-opus-4.6")
    prov = os.environ.get("AIOS_LLM_PROVIDER", "openrouter").lower()
    if prov == "openrouter" and not model.startswith("openrouter/"):
        return "openrouter/" + model
    if prov == "anthropic" and not model.startswith("anthropic/"):
        return "anthropic/" + model
    if prov == "openai" and "/" not in model:
        return model
    return model


def _peer_tool():
    """A CrewAI tool that lets the crew ask another AI OS agent via the hub."""
    try:
        from crewai.tools import tool

        @tool("ask_peer")
        def ask_peer(query: str) -> str:
            """Ask another AI OS agent. Format '<target>: <message>' where target is
            one of: opencode (coding), hermes (autonomous), brain (orchestrator)."""
            target, _, msg = query.partition(":")
            target = target.strip().lower() or "brain"
            body = json.dumps({"to": target, "message": msg.strip() or query}).encode()
            req = urllib.request.Request(HUB + "/api/relay", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.loads(r.read()).get("reply", "")
            except Exception as e:
                return f"(peer '{target}' unreachable: {e})"

        @tool("build_dashboard_ui")
        def build_dashboard_ui(spec: str) -> str:
            """Add a live widget to the AI OS dashboard Canvas. Format 'Title | <html>'
            where <html> is a self-contained HTML snippet (inline CSS/JS, theme vars like
            var(--accent) allowed). Use this to show charts, tables, forms, or dashboards."""
            title, _, html = spec.partition("|")
            body = json.dumps({"op": "add", "title": title.strip() or "widget",
                               "by": "CrewAI", "html": html.strip() or spec}).encode()
            req = urllib.request.Request(HUB + "/api/ui", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=30)
                return "Widget added to the dashboard Canvas."
            except Exception as e:
                return f"(could not add widget: {e})"

        @tool("run_shell")
        def run_shell(command: str) -> str:
            """Run a shell command on this machine (AIOS full control). Guardrailed and
            audited by the hub. Use for inspecting files, git, builds, checking services."""
            if os.environ.get("AIOS_FULL_CONTROL", "1") != "1":
                return "(full control disabled)"
            body = json.dumps({"command": command, "actor": "crewai"}).encode()
            req = urllib.request.Request(HUB + "/api/exec", data=body, method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": "Bearer " +
                                                  os.environ.get("AIOS_HUB_TOKEN", "")})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    d = json.loads(r.read())
                    if d.get("blocked"):
                        return "BLOCKED: " + d.get("err", "")
                    return (d.get("out") or "") + (("\n[stderr] " + d["err"]) if d.get("err") else "")
            except Exception as e:
                return f"(shell error: {e})"

        tools = [ask_peer, build_dashboard_ui]
        if os.environ.get("AIOS_FULL_CONTROL", "1") == "1":
            tools.append(run_shell)
        return tools
    except Exception:
        return []


def run_crew(message: str) -> str:
    from crewai import Agent, Task, Crew, LLM

    key = (os.environ.get("AIOS_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
           or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
    if not key:
        return "⚠️ No model API key set. Run `aios setup --force`, then `aios start crewai`."

    llm = LLM(model=litellm_model(), api_key=key,
              base_url=os.environ.get("AIOS_LLM_BASE_URL") or None)
    tools = _peer_tool()
    operative = Agent(
        role="AIOS Crew Operative",
        goal="Solve the user's request, delegating to other AI OS agents when useful.",
        backstory=("You are a member of The AI OS — a system of six agents. You can call "
                   "opencode for coding, hermes for autonomous work, or the brain for "
                   "orchestration, using the ask_peer tool. You have full control of this "
                   "machine via run_shell (guardrailed + audited). When a visual answer helps, "
                   "you may emit OpenUI Lang (https://www.openui.com) that the dashboard "
                   "renders as a live app."),
        llm=llm, tools=tools, verbose=False, allow_delegation=False,
    )
    task = Task(description=message, expected_output="A clear, helpful answer.", agent=operative)
    crew = Crew(agents=[operative], tasks=[task], verbose=False)
    result = crew.kickoff()
    return str(result)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/health", "/"):
            self._send(200, {"ok": True, "service": "crewai", "model": litellm_model()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            payload = {}
        if self.path in ("/chat", "/kickoff", "/api/chat"):
            msg = payload.get("message", "")
            try:
                reply = run_crew(msg)
                self._send(200, {"reply": reply})
            except Exception as e:
                self._send(200, {"error": f"CrewAI error: {e}"})
        else:
            self._send(404, {"error": "not found"})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"CrewAI service listening on http://127.0.0.1:{PORT}/  (model={litellm_model()})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
