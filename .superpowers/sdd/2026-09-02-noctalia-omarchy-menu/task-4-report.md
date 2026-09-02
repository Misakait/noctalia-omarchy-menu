# Task 4 report — Noctalia panel

## RED / GREEN

- **RED:** `/usr/bin/lua tests/panel_harness.lua` failed before implementation
  with `cannot open panel.luau: No such file or directory`.
- **GREEN:** the same retained-DSL mock harness now passes 9 lifecycle and UI
  contract cases. It drives only inert fixtures and covers render-generation
  invalidation, last-known-good failure handling, timeout/truncation/JSON/schema
  rejection, immediate spawn failure, subtree BFS search, disabled exclusion,
  the eight-row window, input reset, key navigation, pointer/submit activation,
  close-before-dispatch, exact opaque dispatch argv, and callback redaction.

## Files

- `plugin.toml` — API-24 manifest and exact centered exclusive-keyboard panel
  contract.
- `panel.luau` — retained Noctalia menu panel using only the supplied local DSL
  surface.
- `tests/panel_harness.lua` — standard-Lua mock harness for retained nodes,
  lifecycle callbacks, and process invocations.
- `tests/test_panel_contract.py` — manifest and Lua-harness Python contract
  tests.

## Verification

- `/usr/bin/lua tests/panel_harness.lua`: `panel harness: 9 passed`.
- `python3 -m unittest discover -s tests -v`: 67 tests passed.
- `noctalia plugins lint .`: exit 0, `0 errors, 0 warnings`.
  The command emitted three `dconf-CRITICAL` lines because the sandbox cannot
  write `/run/user/1000/dconf/user`; they are environment noise, not lint
  diagnostics.
- `git diff --check`: clean.

## Self-review

- Render callbacks are guarded by both a monotonically increasing generation
  and panel-open state; close invalidates outstanding refreshes without a
  render.
- The model boundary accepts only schema 1 with string revision/root, table
  entries, and an existing root entry. Adapter stdout/stderr are never included
  in refresh or dispatch notifications.
- Action rows have no shell interpolation: the panel closes first and sends
  exactly six argv selectors to the adapter. Disabled rows are visible but
  omit their pointer handler.
- Search consumes only adapter-provided `searchText`, visits the active subtree
  breadth first, and keeps the selected stable ID within an eight-row window.

## Concerns

- Static lint and the Lua harness passed. A live graphical panel smoke test is
  intentionally deferred to Task 6: this task did not start Noctalia, an
  Omarchy shell, or any production action.

## Commit

- `feat(panel): add native Noctalia menu panel` (this Task 4 commit).
