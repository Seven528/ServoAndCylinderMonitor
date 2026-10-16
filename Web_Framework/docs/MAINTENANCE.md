# Website maintenance rules

## Editing workflow

Identify the owning module in `ARCHITECTURE.md`, make a local change, update focused tests, and inspect the real page at wide and narrow widths. Pure tests are necessary but cannot prove visual spacing, focus order or overlay alignment. Keep public DOM IDs and cross-module data fields stable unless all consumers and tests change together.

Read `index.html` before changing selectors. Adjust shared tokens in `style.css`, workspace geometry in `workbench-layout.css`, and side-panel styling in `workbench-panels.css`. Do not grow a second conflicting layout system inside individual event handlers. Use the existing ES module boundaries instead of adding a new framework just for a local edit.

## Interaction invariants

- The main canvas is primary. Side panels must not make the viewport unusable on narrow screens.
- Focus mode restores the user's prior layout. Opening or resizing a panel must not submit analysis or reset manual zoom.
- A request draft is not the displayed result. Never relabel an old image with new control settings before completion.
- Async image/report responses must match the active presentation. Ignore stale work after image, file, mode or session changes.
- File removal needs the existing confirmation and busy-state checks. It withdraws an uploaded identity; original files and reports on disk are retained.
- Default Agent scope is the displayed content. Explicit current-turn filenames/collections may extend it to existing sidebar imports without another upload or mandatory plus-menu confirmation. A checked box alone is not authorization.
- Ordinary replies do not generate report downloads. Export links belong only to the requesting user turn.
- Do not bypass browser/OS microphone permission. Already-ready local dictation can start directly from the microphone action; unavailable resources need explicit setup.
- Keep component picking restricted to the intended mode/view. Preserve exact instance identity rather than selecting by refdes alone.
- Restart creates an empty session. No automatic backup, restored uploads, result selection or conversation replay.

## Resource and security boundaries

Current limits include 64 MiB per upload, 40 cumulative uploads including removed ones, and 64 analyses per session. Preserve bounded report reads, audio buffers, retries, caches and logs. Native analysis and export are admitted through coordinated busy-state gates. Close owned processes, streams and temporary audio through their explicit lifecycle paths.

Render text with escaping; never interpret a file/report/model response as an instruction that grants filesystem access. Do not replace file IDs with arbitrary browser-supplied paths. Keep request validation, Host/Origin checks and capability gates intact.

## Acceptance checklist

- Tests for changed modules pass; native-dependent skips remain explicit.
- Empty page, loading, ready, failed and cancelled states are coherent.
- Wide docked panels, narrow drawers, keyboard focus, Escape and close/return focus work.
- Upload/select/remove and history navigation cannot show a mismatched image or summary.
- Ordinary versus explicitly expanded chat scopes are checked on the host.
- Session restart cannot restore stale results.
- No unsolicited report, hidden model call, sample import, recording or expensive analysis was added.
- Explain what changed, how it was checked and what remains unverified.

## Branding and distribution

The copied Bosch assets retain their original provenance and internal-use boundary. They are not granted a new public license by this handoff. For a different organization or public site, obtain approval or replace the branding. No user credentials, private inputs or analysis reports are needed to change the website framework.
