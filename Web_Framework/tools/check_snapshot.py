"""Check local references and smoke the empty shell without native/Codex services."""

import ast
import json
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source"
WEB = SOURCE / "integrations/local_web_demo/web"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE))

from integrations.local_web_demo.server import DemoServer


def check_link(parent, link):
    if link.startswith(("http:", "https:", "data:", "#", "/")):
        return
    target = link.split("#", 1)[0].split("?", 1)[0]
    assert (parent / target).is_file(), (parent, link)


for path in SOURCE.rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
for path in WEB.rglob("*"):
    if path.suffix not in {".js", ".css", ".html"}:
        continue
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".js":
        links = re.findall(r'(?:from\s+|import\s*)[\'"](\.[^\'"]+)[\'"]', content)
    elif path.suffix == ".css":
        links = [x.strip("\"'") for x in re.findall(r"url\(([^)]+)\)", content)]
    else:
        links = re.findall(r'(?:src|href)="([^"]+)"', content)
    for link in links:
        check_link(path.parent, link)
for path in [ROOT / "README.zh-CN.md", *sorted((ROOT / "docs").glob("*.md"))]:
    for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        check_link(path.parent, link)

with tempfile.TemporaryDirectory(prefix="web-framework-smoke-") as directory:
    server = DemoServer(
        0, Path(directory) / "omitted-engine", Path(directory), with_codex=False
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
            health = json.load(response)
        assert not health["native_ready"] and not health["chat_ready"]
        request = urllib.request.Request(
            base + "/api/state", headers={"X-Demo-Token": health["token"]}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            state = json.load(response)
        assert not state["files"] and not state["jobs"] and not state["messages"]
        for path in WEB.rglob("*"):
            if path.is_file() and path.suffix != ".md":
                with urllib.request.urlopen(
                    base + "/" + path.relative_to(WEB).as_posix(), timeout=5
                ) as response:
                    assert response.read() == path.read_bytes(), path
        try:
            urllib.request.urlopen(base + "/api/state", timeout=5)
            raise AssertionError("Unauthenticated state access unexpectedly allowed")
        except urllib.error.HTTPError as error:
            assert error.code == 403
        print(
            "PASS: Python syntax, local links/imports, static HTTP resources, empty shell, disabled integrations and token gate"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.close_owned()
