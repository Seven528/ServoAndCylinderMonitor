# Website framework and module map

## Architecture

The site uses native HTML, CSS and browser ES modules. There is no React/Vue runtime, npm application build, bundler, database or frontend distribution directory. Python's ThreadingHTTPServer serves the static files and local API. The existing domain engine runs behind an MCP adapter; it is not the web framework and is deliberately excluded.

```text
index.html + style.css
          |
        app.js                composition, polling, lifecycle
          |
  result-state.js            request draft != displayed result
     /    |      \
controls viewer  file/chat/layout panels
          |
     transport.js            health handshake, token, session checks
          |
       server.py             loopback HTTP, API, SSE, shutdown
       /       \
storage.py     conversation.py -> codex_bridge.py -> optional Codex runtime
    |                 |
analysis.py      turn_scope.py / file_targets.py / tool_parameters.py
    |
external native engine through pcbuni_adapter (not included)
```

All paths below are relative to `source/integrations/local_web_demo/`.

## Frontend ownership

| Area to change | Files | Responsibility |
| --- | --- | --- |
| Page skeleton and accessible anchors | `web/index.html` | Header, navigation rail, drawers, controls, viewport, composer and dialogs; DOM IDs are consumed by modules |
| Tokens and common appearance | `web/style.css` | Colors, typography, controls, result styles; imports the other two stylesheets |
| Responsive shell | `web/workbench-layout.css` | Header, workspace geometry, rail, docked panels, drawers and responsive sizing |
| Panel appearance | `web/workbench-panels.css` | File/history/chat panels and composer styling |
| Composition and lifecycle | `web/app.js` | Connect, poll, ingest, render, bind actions, session reset; avoid turning this into a business-algorithm module |
| Layout behavior | `web/layout-state.js`, `web/layout.js` | Pure panel preference projection plus DOM/focus/Escape behavior |
| Controls and result identity | `web/controls.js`, `web/result-state.js`, `web/result-view.js`, `web/summary.js` | Draft parameters, selected presentation, result links and statistics |
| Image viewport | `web/viewer.js`, `web/image-loader.js`, `web/image-download.js` | Image loading/recovery, zoom, pan, export and coordinate overlay integration |
| Files and history | `web/file-panel.js`, `web/history-subjects.js` | Upload/list/select/remove and source labels; removal is session withdrawal, not physical source deletion |
| Chat and model UI | `web/chat-panel.js`, `web/model-picker.js`, `web/chat-connection.js` | Composer, stream display, settings and connection state |
| Network and recovery | `web/transport.js`, `web/connection-recovery.js` | Token handshake, HTTP errors, session identity and bounded backoff |
| Automatic preview | `web/auto-preview.js` | Debounced preview scheduling, caching/selection and cancellation coordination |
| Conversation authority | `web/canvas-scope.js` | Project the actually displayed presentation into the request; not the final authority gate |
| Optional exports | `web/report-request.js`, `web/message-downloads.js` | User-requested reply downloads only |
| Optional speech | `web/dictation.js`, `web/dictation-control.js`, `web/local-recognition.js` | Microphone lifecycle, PCM conversion, local transcription request and composer insertion |
| Domain-bound picking | `web/pressure-picking.js`, `web/pressure-details.js` | Existing pressure-head UI and exact component highlighting; reference, not a generic geometry library |
| Text and assets | `web/text.js`, `web/assets/`, `web/favicon.svg` | Escaping/formatting and local visual assets |

## Backend ownership

| Module | Website responsibility | Business coupling |
| --- | --- | --- |
| `server.py` | HTTP routing, static assets, request security, SSE, resource shutdown | Endpoint names, sample route and capability fields reflect the current product |
| `storage.py` | Bounded uploads, IDs, artifacts, source protection and file revision | Current roles/extensions and report queries are domain-specific |
| `analysis.py` | Single-flight jobs, cancellation, result publication | Native MCP invocation and job arguments |
| `presentation.py` | Associate image, report, source and view into one display identity | Maps native domain outputs |
| `conversation.py`, `codex_bridge.py` | Controlled tool calls, streamed turns, owned subprocess lifecycle | Prompt, tool names and scope policies must be adapted together |
| `turn_scope.py`, `file_targets.py` | Per-turn authorization and explicit uploaded-file resolution | Role vocabulary and matching examples depend on the app |
| `tool_parameters.py` | Validate arguments before creating a job | Uses the serving engine's schema |
| `image_exports.py`, `pressure_picking.py` | Image export and read-only interaction data | Native formats/report geometry |
| `local_speech.py`, `speech/main.swift` | Bounded local speech and cancellation | Optional macOS platform integration, not PCB logic |

The sibling `azure_agent/pcbuni_adapter` files are included because Python imports them, including the package initializer's service import. This does not make Azure a required web deployment target.

## Reusing the framework for another application

Reuse layout, drawer/focus handling, request-versus-result separation, transport recovery, streaming composer, upload IDs and lifecycle patterns. Replace role vocabulary, controls, report projection, native adapter and tool schemas at their boundaries. Update all consumers and tests together. Do not copy domain interpretation into `viewer.js` or infer identity from a filename substring.

The source snapshot intentionally remains unchanged. A reusable pattern is not the same as an already extracted generic library. For visual work, start with CSS and the owning DOM module; a new React/Vue stack is neither required nor provided.
