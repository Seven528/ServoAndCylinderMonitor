# HTTP and state contracts

## Connection and security

`web/transport.js` first calls `GET /api/health`, retains its token and `server_id`, and sends `X-Demo-Token` for protected requests. The server checks Host and checks Origin on writes. Do not log the token or transplant it into examples. Request bodies, IDs and report ownership are validated on the host, not trusted because the browser produced them.

The handshake advertises native/chat readiness, model/default settings, speech capability and versioned optional UI features. Current version-1 gates cover canvas scope, explicit file scope, file removal, pressure picking and component highlighting. Availability comes from the running backend, not a hardcoded optimistic UI flag.

## Endpoint map

The executable contract is `source/integrations/local_web_demo/server.py`; this table is a navigation aid, not a replacement schema.

| Method and route | Use |
| --- | --- |
| GET `/api/health` | Connection handshake and capabilities |
| GET `/api/state` | Session snapshot: IDs, selection, files, revision, jobs, busy flags and messages/settings |
| POST `/api/upload?name=...&role=...` | Raw uploaded bytes and Content-Length, not multipart; host returns file ID |
| POST `/api/selection` | `{pcb_ids: [...], holder_id: ...}`; selection alone does not authorize Agent work |
| POST `/api/files/remove` | `{file_id: ...}`; returns updated state and withdraws dependent results |
| POST `/api/analysis` | `{arguments: ..., label: ...}`; starts a bounded job |
| POST `/api/analysis/cancel` | `{job_id: ...}` |
| GET `/api/report` | Bounded structured report queries |
| GET `/api/artifacts/<id>` | Registered image/report bytes; optional download query |
| GET `/api/pressure-picking` | Read-only presentation-bound hit data and paged head details |
| POST `/api/export-image` | Native-backed export of the selected source/view |
| POST `/api/chat` | Turn request, frozen scope and SSE response |
| POST `/api/chat/cancel` | Stop the owned active turn |
| POST `/api/dictation` | Local PCM WAV with `audio/wav` and request identity |
| POST `/api/dictation/prepare` | Explicit offline model preparation, no recording body |
| POST `/api/dictation/cancel` | `{request_id: ...}` |
| POST `/api/samples` | Original-project sample loader; samples omitted from this package |

SSE uses `event: ...` and a JSON `data: ...` line, separated by a blank line. `conversation.py` and `codex_bridge.py` define the emitted event types; `chat-panel.js` consumes them. Keep completion, cancellation and error states distinct. A page refresh does not itself cancel a running turn.

## State identity

Keep these separate:

- `draft`: controls for a future request.
- `selection`: sidebar selection of files.
- `presentation`: actual source, image, report and view currently selected for display.
- `server_id` and `session_id`: current backend/session identity.
- `file_revision`: monotonic protection against a delayed snapshot resurrecting removed files.

`app.js` refreshes state on a one-second timer and periodically refreshes health. `connection-recovery.js` backs off after failures. Local view preferences are checked against session identity before restoration. The versioned layout preference is a visual preference, not permission to restore old files or analysis.

For chat, the browser sends the displayed presentation identity only after the image is genuinely ready. The host resolves source/report IDs. A current explicit user request can resolve other uploaded files or a collection through `file_targets.py`; the authority is frozen for that turn. Ambiguity asks for clarification rather than selecting arbitrary files. The next unspecified turn returns to the current canvas.

For future domain integrations, preserve ID-based access, stale-response rejection, cancellation, capability negotiation and per-turn authorization. Replace domain arguments and result projection rather than weakening the host gate.
