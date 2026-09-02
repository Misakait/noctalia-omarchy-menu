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

The inventory must contain all 270 stock actions and both providers from the current
`/usr/share/omarchy/default/omarchy/omarchy-menu.jsonc`, with expected action/provider
signatures. Every entry is exactly one of pass-through, mapped, provider, or disabled.
Unknown stock `omarchy-*` helpers are disabled as `Compatibility not reviewed`; a
changed signature bypasses an exact rule. Opaque helper rules record the SHA-256 of
the audited helper and its relevant `omarchy-*` dependency closure; missing/changed
digests downgrade that rule to `Compatibility not reviewed`.

Exact mappings:

- `apps` opens `noctalia msg panel-open launcher`; `about` keeps
  `omarchy-launch-about`.
- `learn.keybindings` uses `niri msg action show-hotkey-overlay`.
- screenshot uses `niri msg action screenshot`; text/QR use plugin-local scripts
  with `slurp`, `grim`, `tesseract`/`zbarimg`, and `wl-copy`; color uses
  `niri msg pick-color`.
- three non-webcam screen-record actions keep their original argv with
  `OMARCHY_SCREENRECORD_USE_PORTAL=true`; stop remains pass-through; webcam is
  disabled.
- idle, notification, nightlight, top-bar, and battery-percentage rows map to
  Noctalia IPC (`caffeine-toggle`, `notification-dnd-toggle`,
  `nightlight-force-toggle`, `bar-toggle`, and `settings-open bar`).
- theme/background/bar rows open Noctalia appearance, wallpaper, or bar UI.
- monitor/keybinding/input setup rows open `~/.config/niri/config.kdl` through
  `omarchy-launch-config-editor`; clear their Hyprland-specific guards.
- lock maps to `noctalia msg session lock`; logout maps to
  `niri msg action quit --skip-confirmation`; reboot/shutdown use plugin-local
  wrappers preserving the two-second `systemd-run` scheduling before quitting Niri;
  suspend and hibernate remain direct systemctl actions.
- fonts are regenerated from `omarchy-font-list`/`omarchy-font-current`; selecting
  one uses a plugin-local safe argv wrapper which mirrors `omarchy-font-set` but does
  not call `omarchy-restart-shell` or start Omarchy Shell.

Exact disabled as `Hyprland only`: `system.screensaver`, webcam recording,
`trigger.hardware.laptop-display`, `mirror-display`, `touchpad`, `touchscreen`,
workspace layout/window gaps/one-window ratio/screensaver toggles, `style.hyprland`,
all `style.screensaver.*`, `setup.config.hyprland`, `setup.config.hyprsunset`,
`update.process.hyprsunset`, `update.config.hyprland`, and
`update.config.hyprsunset`.

Exact disabled as `Omarchy Shell only`: emoji, interactive reminder, both speed
tests, Wi-Fi QR, every `setup.plugin.*` action, unlock switcher, shell restart/reset,
and the Tmux/Herdr keybinding selector.

Exact disabled as `Compatibility not reviewed`: interactive transcode, retro game
launcher, theme/webapp/TUI removal selectors, timezone selector, install/remove
Voxtype, Windows VM, preinstalls, Dropbox and Tailscale service integration, and
theme installation. Remaining audited stock actions pass through unchanged so their
downstream prompts remain intact. Supported providers are `apps` and `fonts`; any
other provider remains visible disabled as `Unsupported provider`.

Write tests first for inventory coverage, signature matching, digest downgrade,
provider token changes, mapped dependency disabling, and helper scripts in inert
test modes or controlled temporary homes. The audit must read/classify only; it must
not dispatch a row.

## Task 3: Adapter CLI and detached execution

Implement `render`, `audit`, and `dispatch REVISION ID TOKEN`. Dispatch rebuilds the
model, validates the selection, and detaches the resolved action with closed standard
streams. Add fixtures proving stale and invalid selections cannot spawn and a safe
long-lived/noisy child does not hold the adapter open.

Production defaults are the fixed system menu, user extension, and plugin-local
compatibility paths from the approved design. Tests may inject alternate paths and
runners. Loading compatibility requires a JSON object of rules; malformed or partial
sources are errors and never silently produce a smaller menu.

The system source is required; an absent extension is the one valid empty-extension
case. Parse JSONC with duplicate-key detection. Reject empty or reserved `root` IDs,
wrong types for action/provider/guard fields, truncated input, a missing/non-object
compatibility rules map, unknown compatibility schema versions, and malformed
match/mode/dispatch/requires/digests/env values. Unknown descriptive menu fields remain
forward compatible. An invalid source or compatibility document fails the whole build
before stdout is written; it never yields a partial model.

Build one model through the same path for render and dispatch:

- reread both menu sources and compatibility on every call, merge by ID/field, and
  compute the revision from the merged raw menu plus compatibility content (never
  from volatile guard/provider results);
- preserve an exact stock compatibility rule for label/icon/description-only user
  overrides, while treating a new ID or an action/provider change as extension-owned;
- fail closed when a system-source entry has a known exact rule whose signature drifts;
  only extension-owned overrides may use generic compositor-neutral pass-through;
- resolve compatibility before providers and guards, expand providers with bounded
  capture, combine warnings, finalize the hierarchy/search metadata, and redact all
  action/guard/raw-provider payloads from the view model while retaining the normalized
  non-sensitive provider identifier required by the public schema;
- run each trusted guard with `bash -lc` and the exact source expression, a 1.5 second
  timeout, `start_new_session`, and closed standard input; on timeout kill its process
  group and reap it. The per-expression timeout starts when that subprocess starts, not
  while work waits behind the eight-worker pool. Preserve the existing eight-second
  atomic batch deadline and ensure deadline failure cannot leave executor workers or
  descendants holding the CLI open;
- capture providers as bytes with a 1.5-second timeout, 256 KiB total stdout limit,
  4,096-byte line limit, and 2,048-row limit. Invalid UTF-8, NULs, timeout, overflow,
  or a nonzero exit rejects that provider expansion atomically, emits only a
  non-sensitive warning, and leaves its provider menu visible without partial rows.

Freeze the public view schema before the panel is written. The top-level keys are
`schemaVersion`, `revision`, `root`, `entries`, `warnings`, and `source`; `root` is the
synthetic root entry ID. `source` exposes only the Omarchy package string and whether
the optional extension was loaded. Entry keys use lower camel case:
`id`, `parent`, `kind`, `icon`, `iconFont`, `label`, `title`, `target`, `description`,
`aliases`, `provider`, `header`, `children`, `visible`, `enabled`, `checked`, `disabled`,
`compatibilityStatus`, `disabledReason`, `order`, `breadcrumb`, `searchText`, and
optional `actionToken`. Issue a token only for a currently visible, enabled actionable
leaf. Explicit allow-list and serialized-leakage tests forbid `action`, `dispatch`,
raw guards, provider output/values, or effective-guard internals.

The CLI contract is:

- `render` writes exactly one schema-versioned JSON object to stdout;
- `audit` is read-only, reports classification/digest coverage, and exits nonzero for
  an incomplete or invalid inventory;
- `dispatch REVISION ID TOKEN` rebuilds the model, validates all three opaque
  selectors plus visibility/enabled/action kind, spawns the resolved action, and
  returns without waiting for the action result;
- failures use stable exit categories and a bounded structured stderr record containing
  only category, entry ID when safe, and adapter exit code—never a command, environment,
  guard expression, provider output, raw action, traceback, or argparse usage text.
  A reported ID is limited to 128 safe identifier characters; omit it otherwise.

Resolve action payloads only after successful validation. Shell actions execute as
`bash -lc` with the exact trusted action string; argv actions stay argv. Plugin-local
scripts must resolve below the adapter directory, reject traversal, and be executable.
All dispatched children use `start_new_session=True`, `close_fds=True`, and
`stdin/stdout/stderr=DEVNULL`, with a copied environment plus only the fixed mapping
declared by compatibility. A single post-validation executor rejects malformed payload
unions, empty argv, NUL arguments/environment, absolute or escaping script paths,
escaping symlinks, directories, non-executable files, and missing commands/scripts
before spawn. Map process-start exceptions to the stable start-failure category.

Write failing tests first for temporary-source end-to-end render/dispatch, malformed
source and compatibility errors, extension ownership, revision stability, stale
revision/token rejection, unknown/menu/hidden/disabled rejection, script containment,
guard descendant cleanup/races/queueing, provider bounds and atomic failure, and
stderr/view-model allow-list redaction. Assert a spawn sentinel stays at zero for every
rejected selection and malformed payload. A safe
fixture child may write a marker under a temporary directory; it must survive adapter
exit, emit arbitrarily noisy output without corrupting JSON, and prove dispatch returns
promptly. Assert the rendered stock model exposes the ten approved root categories.
Invoke subprocess end-to-end tests from outside the project directory as well. No test
may execute a real stock menu action.

## Task 4: Noctalia panel

Implement `plugin.toml` and `panel.luau` with generation-safe async refresh,
last-known-good behavior, search/navigation/paging, disabled rows, Launcher bridge,
and safe adapter error notifications. Validate the plugin with Noctalia lint.

The manifest uses plugin API 24, plugin ID `misakait/omarchy-menu`, panel ID `menu`,
and a 440 by 560 centered floating panel with exclusive keyboard focus. Capture
lowercase `up`, `down`, `prior`, `next`, `left`, and `right`; Escape remains owned by
the host. The panel is implemented with Noctalia's retained declarative Luau API and
starts no background process.

Each `onOpen` increments a generation, marks loading, and calls
`python3 <pluginDir>/menu_adapter.py render` as argv with a ten-second callback timeout.
Reject nonzero exit, timeout, either truncation flag, malformed JSON, an unsupported
schema version, or missing revision/root/entries types. A callback from an older
generation or a closed panel cannot mutate current state. Failed refreshes keep the
last known good model visible with an inline error/retry banner; the first failure
shows a bounded error state. Retry starts a new generation. Treat an immediate `false`
return from `noctalia.runAsync` as a spawn failure because no callback will arrive.
`onClose` marks the panel closed and increments the generation to invalidate every
pending render callback without rendering again. Decode with
`pcall(noctalia.json.decode, stdout)` and validate `entries[root]` before replacement.

Use a focused uncontrolled `ui.input`; changing its component key resets it when the
Clear affordance is used. Empty search shows the current menu's direct children.
Nonempty search scans the active subtree using adapter-supplied `searchText`, excludes
disabled rows, and orders direct children before deeper breadth-first matches. Because
the API has no scroll-to-index, render a stable visible window of exactly eight rows
around the selected index and show its range/total. Keep selection by stable ID and
fall back to the first activatable row when filtering/navigation invalidates it.

Keyboard behavior applies only on pressed events: Up/Down move across activatable
rows, Prior/Next move a page, Right activates, Left navigates to the parent, and input
submit activates the current (or first activatable) row. Menu/link rows navigate in
the existing model. Action rows close the panel first, then invoke exactly
`python3 <adapter> dispatch <revision> <id> <actionToken>` as argv. Dispatch callbacks
remain active after close and may report only a bounded category/ID/exit-code error,
never payloads or adapter stdout/stderr. This same action path makes `apps` close this
panel and open Noctalia Launcher through the adapter.

Normal browsing keeps incompatible entries visible but inert, with reduced opacity
and their adapter-provided reason. Render raw Unicode menu icons as labels, not glyph
names. Include Back, Close, Clear, Retry, loading, warnings, breadcrumb, and concise
navigation hints without depending on shell-specific components.

Use only APIs present in the installed retained DSL: `ui.row({ onClick = ... }, ...)`
or `ui.button` for pointer activation (there is no `ui.clickable`), `ui.input` with
`focus = true`, a revision-based `key`, `onChange`, and `onSubmit`,
`noctalia.runAsync`, `noctalia.json.decode`, `noctalia.notifyError`, and
`panel.close()`. Disabled compound rows omit `onClick`; do not merely rely on opacity.

Add contract tests for the manifest and adapter invocation/error-redaction surface,
plus pure state/search/windowing tests wherever logic can be isolated from the host.
Use only inert fixtures. Run the repository tests and `noctalia plugins lint`; do not
open or dispatch any real stock action during validation.

## Task 5: Install and Niri integration

Install the plugin at `~/.local/share/noctalia/plugins/omarchy-menu`, enable it for
the next Noctalia start when IPC is unavailable, replace only `Mod+Alt+Space`, add
the two Omarchy floating app-id rules, and perform candidate/pre/post validation with
rollback on failure.

Stage a direct runtime copy (manifest, panel, adapter, compatibility file, and helper
scripts) beside the final plugin directory, preserve modes, and lint the staged plugin.
If a previous installation exists, rename it to a timestamped recoverable backup; then
atomically rename the staging directory into place. Do not install a symlink and do not
copy repository metadata, test fixtures, or the SDD workspace.

Enable `misakait/omarchy-menu` through Noctalia IPC when a live daemon is available.
Otherwise update only the enabled-plugin array in
`~/.local/state/noctalia/settings.toml` through a same-directory candidate, validate
the candidate, create a timestamped backup, and atomically replace the live file.
Preserve every unrelated setting and avoid duplicate IDs.

For `~/.config/niri/config.kdl`, create a same-directory candidate and change only the
existing `Mod+Alt+Space` action from Noctalia control center to
`noctalia msg panel-toggle misakait/omarchy-menu:menu`. Leave `Mod+Space` Launcher and
the Noctalia clipboard binding untouched. Add floating rules matching
`org.omarchy.about` and `org.omarchy.terminal`. Validate the candidate with Niri,
create a timestamped backup of the current live file, atomically replace it, and
validate the live result. Any post-validation failure restores the backup before
returning an error.

After installation, lint the final plugin and validate both live configuration files.
If Niri/Noctalia IPC is unavailable, record that live UI reload/smoke is deferred to
the next graphical session rather than starting an extra shell or compositor process.

## Task 6: Final verification and review

Run the full unit suite, adapter audit/render checks, Noctalia lint, Niri validation,
and all safe live checks available in the current session. Conduct an independent
whole-project review and fix all blocking findings before completion.
