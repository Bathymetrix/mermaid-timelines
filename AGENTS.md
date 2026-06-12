# AGENTS.md

Guidance for coding agents working in this repository.

## Collaboration Rules

- When a coherent work unit is complete, tell the user whether it is a good time to commit and suggest a concise commit message. Use a plain, sensible, capitalized message rather than a `<type>: message` convention.
- Any time you suggest a commit message, also bump version (`major`, `minor`, or `patch`) and alert user.
- When the thread has accumulated enough context that a fresh thread would be cleaner, especially for token or context-window reasons, tell the user it is a good new-thread point.
- When recommending a new thread, provide a compact context handoff that summarizes the goal, current state, changed files, verification results, and next steps.
- When CI status matters and the GitHub CLI is available, use `gh run list` and `gh run view` to check the relevant GitHub Actions run. Report the workflow conclusion and matrix job conclusions, especially Python-version matrix entries.

## Namespace Consolidation / Public API Discipline

AGENTS should keep future namespace consolidation in mind during all implementation and API decisions.

## Instrument Terminology

- Refer to full names such as `467.174-T-0100` as the **instrument serial**.
- Refer to canonical 5-character station names such as `T0100` as the
  **instrument ID**.
- Keep this distinction clear in CLI flags, schema/docs, tests, diagnostics,
  commit messages, and user-facing explanations.

This project may eventually become part of a larger unified namespace layout such as:

```text
src/mermaid_records/   -> src/mermaid/records/
src/mermaid_timeline/  -> src/mermaid/timeline/
src/mermaid_telemetry/ -> src/mermaid/telemetry/
src/mermaid_gcmt/      -> src/mermaid/gcmt/
```

Therefore:

- Prioritize stable CLI/file-format contracts over stable internal import paths.
- Keep public Python API exposure intentionally small.
- Avoid exposing internal helpers/classes/functions unless clearly intended as durable public API.
- Avoid documenting deep import paths as stable interfaces.
- Prefer CLI-driven workflows over broad import-driven workflows.

Key philosophy:

- The primary public contract is:
  - CLI behavior
  - documented file formats/schemas
  - manifests/state behavior
  - documented validation behavior
- Internal Python module layout is NOT yet considered stable public API.

Guidelines:

- Avoid unnecessary re-exports in `__init__.py`.
- Internal modules/functions/classes may be reorganized freely unless explicitly documented as public API.
- Prefer stable CLI entry points and stable JSONL/file contracts over stable internal module paths.
- Use centralized constants/helpers for package metadata where practical (package name, schema version, filenames, etc.) rather than scattering hardcoded package names throughout the codebase.
- Do not over-engineer namespace-package machinery prematurely; just avoid choices that would make later migration painful.
- Before exposing/importing/re-exporting new symbols publicly, consider whether doing so creates a long-term compatibility obligation.
- When introducing new public APIs, consider whether they would remain sensible after a future migration from:

  ```text
  mermaid_<thing>
  ```

  to:

  ```text
  mermaid.<thing>
  ```

- Tests may import internal modules freely; test imports are not considered stable public API.
