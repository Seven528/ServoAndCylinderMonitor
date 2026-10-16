# Website modification handoff prompt

You are modifying an existing website, not designing or validating PCB algorithms. Start with README.zh-CN.md, ARCHITECTURE.md, BUILD_AND_RUN.md and HTTP_AND_STATE.md. Inspect the current code under source/integrations/local_web_demo/web before proposing changes.

The implementation is native HTML/CSS/ES modules with a local Python HTTP service. Preserve the small module structure. Keep page layout, result identity, transport and domain adapter responsibilities separate. Do not introduce React, a database, a remote upload service or a replacement geometry engine unless the owner explicitly requests it.

Ask for the desired webpage modification if no concrete change is supplied. For an agreed change, identify affected files and contract surfaces, implement the smallest complete change, add focused tests and verify the actual wide/narrow UI. Do not claim a skipped native or browser test passed.

Source in this folder is a byte-for-byte working-tree snapshot, not necessarily a committed revision. Use MANIFEST.json to verify it before editing. Do not overwrite a colleague's newer work by copying the whole folder over their checkout. After making changes, supply a focused diff and the verification receipt.

Preserve current behavior: Agent defaults to the actual main canvas; explicit current-turn file or collection requests can use existing sidebar imports; checkboxes alone do not grant scope; reports are opt-in; restart opens a fresh empty session without automatic backup/restoration; physical original files and reports are not deleted. Do not test by recording a microphone, sending remote model content or running analysis on real files without appropriate authorization.

The package excludes the native engine, UNI samples, credentials and model assets. Shell-only mode intentionally reports unavailable integrations. Use mocks only when clearly labeled as mocks, and do not fabricate analysis success or engineering evidence.

Return: changed files, interaction changes, executed tests, visual verification, remaining prerequisites, and concise launch instructions. Keep user communication in Chinese unless requested otherwise.
