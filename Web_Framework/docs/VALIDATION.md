# Handoff validation

## Scope and source identity

Prepared 2026-10-16 from the current `feature/agent-cli-mode` working tree, based on HEAD `dc4b3dfe12df18c494e7abf058e54d6faf884f3b`. The source includes uncommitted and untracked web changes; this is not a clean-commit release. The manifest's hashes identify the delivered files.

The package contains 81 unchanged source/reference files, including the current web modules, backend, tests, optional Swift source, native feature configuration, required Python adapter imports and visual-asset provenance. Native code, historical project plans, PCB samples, real reports, sessions, binaries, environments and credentials are excluded. `DESIGN_REFERENCES.md` is a dated design reference; current CSS/source takes precedence over historical dimensions or decisions in that reference.

## Tests executed from the copied source

| Check | Result |
| --- | --- |
| Node frontend tests | 81 passed, 0 failed, 0 skipped |
| Python tests | 82 discovered, 70 passed, 12 skipped, 0 failed; 3.810 seconds |
| Copied shell smoke | Passed on an isolated ephemeral HTTP port; empty state, static resources and token gate verified |
| Python syntax and local references | Passed for copied Python, frontend imports/assets and handoff document links |

Test tools on the authoring machine: Node v26.0.0 and Python 3.14.6. These are observed versions, not a lockfile or a claim that every older runtime was tested.

The Python tests used the already installed repository venv interpreter with bytecode writes disabled, but imported and executed the copied source tree. The 12 skips require the deliberately omitted native executable/fixtures. They are not native acceptance results. No account, model invocation, microphone recording or real input analysis was needed.

## Reproduce package checks

Before editing or creating a venv inside the package:

```sh
python3 tools/verify.py
```

After installing the source requirements, from the handoff root:

```sh
source/.venv/bin/python tools/check_snapshot.py
```

The snapshot check parses Python, resolves local frontend imports/assets and handoff documentation links, then starts the copied backend on an ephemeral port with an intentionally missing native executable and Codex disabled. It checks static resources, health, empty files/jobs/messages and denied unauthenticated state access, then closes its owned server. Runtime data uses a temporary test directory, never the running site's directory.

## Delivery limits

This is a source handoff for website modification. No fresh-machine dependency installation, browser visual acceptance, native build, remote-model integration, speech setup or Windows run is claimed. Existing source tests remain available to guide changes. Production hosting and generic-framework extraction are outside this package.

The currently running website was not edited or restarted. Historical handoff folders were not replaced. New recipients should run the integrity check first, then the shell and focused tests for their intended changes.
