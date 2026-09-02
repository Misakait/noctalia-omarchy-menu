# Noctalia Omarchy Menu implementation plan

Spec: `/home/misakait/docs/superpowers/specs/2026-09-02-noctalia-omarchy-menu-design.md`

## Global constraints

- Never write below `/usr/share/omarchy`; both Omarchy menu inputs are reread for every render and dispatch.
- Never execute update, install, remove, factory-reset, logout, suspend, hibernate, reboot, or shutdown during verification.
- `Super+Space` remains Noctalia Launcher; only `Super+Alt+Space` is replaced.
- The plugin starts no Omarchy Shell process. Unsupported entries remain visible and disabled.
- Actions receive no plugin confirmation; downstream confirmations are preserved.
- Adapter output contains no raw action command and dispatch validates revision, ID, token, visibility, and enabled state.
- The live Niri file changes only after same-directory candidate validation and a timestamped backup.

## Task 1: Core adapter

Implement JSONC loading, per-field overlay merge, normalization, guard evaluation,
compatibility-before-guard resolution, safe hierarchy/search, revision/action tokens,
view-model redaction, and dispatch validation. Cover behavior with unit tests written
and observed failing before their implementation.

## Task 2: Compatibility inventory and mapped scripts

Inventory every current system action/provider in `compatibility.json`. Implement
the Niri-safe OCR/QR/font helpers and supported provider expansion. Add a dry-run
audit which fails on an unclassified current system entry. Never invoke an action.

## Task 3: Adapter CLI and detached execution

Implement `render`, `audit`, and `dispatch REVISION ID TOKEN`. Dispatch rebuilds the
model, validates the selection, and detaches the resolved action with closed standard
streams. Add fixtures proving stale and invalid selections cannot spawn and a safe
long-lived/noisy child does not hold the adapter open.

## Task 4: Noctalia panel

Implement `plugin.toml` and `panel.luau` with generation-safe async refresh,
last-known-good behavior, search/navigation/paging, disabled rows, Launcher bridge,
and safe adapter error notifications. Validate the plugin with Noctalia lint.

## Task 5: Install and Niri integration

Install the plugin at `~/.local/share/noctalia/plugins/omarchy-menu`, enable it for
the next Noctalia start when IPC is unavailable, replace only `Mod+Alt+Space`, add
the two Omarchy floating app-id rules, and perform candidate/pre/post validation with
rollback on failure.

## Task 6: Final verification and review

Run the full unit suite, adapter audit/render checks, Noctalia lint, Niri validation,
and all safe live checks available in the current session. Conduct an independent
whole-project review and fix all blocking findings before completion.
