# Build and run memo

## Website only

Frontend files are served as written. There is no `npm install` or `npm run build` step for this application. Use HTTP, not `file://`, because ES modules and API requests require a server. Node is needed only for the frontend tests.

From the handoff directory, prepare Python 3.11 or later:

```sh
cd source
python3 -m venv .venv
.venv/bin/python -m pip install -r integrations/local_web_demo/requirements.txt
.venv/bin/python -m integrations.local_web_demo.server --port 8894 --without-codex
```

Open the local address printed by the server. The shell is usable for layout inspection without the omitted native executable, but analysis and chat are unavailable. This is a deliberate degraded mode, not simulated analysis. The sample-import endpoint also needs the omitted original samples. Do not use it as a standalone demo-data loader.

The server binds to loopback only. If the requested port is occupied, current code falls back to a dynamic port; always read the printed URL. Use a separate port while colleagues test. Stop with Ctrl+C, which invokes owned-resource shutdown. Do not kill unrelated Python processes.

On Windows, the venv interpreter is `.venv\Scripts\python.exe`; the shell source is portable Python/JS, but the optional speech helper is macOS-only and this handoff was not validated on Windows.

## Full integration in the original project

The original project launcher `启动PCB演示.command` prepares the venv, compiles/signs the Swift helper, configures CMake Release and builds the native target before starting the server. It is not included here because it requires the excluded native repository. Do not run a partial native build from this package.

In a complete authorized checkout with the native build available:

```sh
build/local-web-demo/venv/bin/python -m integrations.local_web_demo.server --port 8890
```

Supported options in the copied `server.py`:

| Option | Purpose |
| --- | --- |
| `--port` | Requested loopback port, default 8890 |
| `--executable` | Path to compatible native executable; default `build/cpp/release/cpp/PCBUNIInspectorAgent` below the source root |
| `--runtime-root` | Parent for a new UUID session directory; default `build/local-web-demo/runs` |
| `--without-codex` | Disable the chat bridge, useful for shell/native diagnostics |
| `--open` | Ask the OS to open the actual bound address |

The chat bridge locates Codex through `PCB_DEMO_CODEX_BIN`, an existing bundled app path, or PATH. Credentials and account configuration are deliberately not supplied. Chat can use a remote model; local geometry and on-device dictation do not imply that all chat content stays local. Have the recipient review their data policy before enabling model calls.

Speech requires the compiled Swift helper at `build/local-web-demo/speech/PCBLocalSpeech`, supported macOS speech APIs, the approved offline locale model and user microphone permission. This package contains only its source. Do not download models, record audio or change privacy permissions merely to inspect the UI.

## Tests

From `source/`:

```sh
node --test integrations/local_web_demo/tests/*.mjs
.venv/bin/python -m unittest discover -s integrations/local_web_demo/tests -q
```

Tests needing the native executable and UNI fixtures skip in this source-only handoff. The pure browser tests use Node's test runner; passing them does not establish responsive visual quality. See `VALIDATION.md` for this package's actual results.

## Restart and troubleshooting

1. Identify the process actually listening on the requested port, not an old remembered PID.
2. Gracefully stop only that application's backend; wait for listener release.
3. Start the intended source checkout and verify `/api/health` plus actual bound port.
4. Reload the page. A new `server_id` must reset session-bound UI, uploads, results and messages. Do not restore old state or create an automatic conversation backup.
5. Confirm zero files/jobs/messages for a fresh session. Original disk artifacts remain untouched.

An old capability version or disabled new control can mean stale backend code. An unavailable native engine is expected in this package. A 403 can be an expired token or wrong Host/Origin; reconnect instead of weakening the checks. A layout-only static server can serve the HTML, but without `/api/health` and `/api/state` it is not an integrated workbench.

This is a local development service, not an authenticated multi-user production deployment. Publishing externally requires separate security, identity, isolation and hosting work.
