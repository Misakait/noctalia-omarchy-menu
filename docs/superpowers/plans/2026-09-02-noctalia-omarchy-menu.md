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

Build one model through the same path for render and dispatch:

- reread both menu sources and compatibility on every call, merge by ID/field, and
  compute the revision from the merged raw menu plus compatibility content (never
  from volatile guard/provider results);
- preserve an exact stock compatibility rule for label/icon/description-only user
  overrides, while treating a new ID or an action/provider change as extension-owned;
- resolve compatibility before providers and guards, expand providers with bounded
  capture, combine warnings, finalize the hierarchy/search metadata, and redact all
  action/provider/guard payloads from the view model;
- run each trusted guard with `bash -lc` and the exact source expression, a 1.5 second
  timeout, `start_new_session`, and closed standard input; on timeout kill its process
  group. Preserve the existing eight-second atomic batch deadline;
- bound provider capture time and output size so a broken helper cannot hang or flood
  render.

The CLI contract is:

- `render` writes exactly one schema-versioned JSON object to stdout;
- `audit` is read-only, reports classification/digest coverage, and exits nonzero for
  an incomplete or invalid inventory;
- `dispatch REVISION ID TOKEN` rebuilds the model, validates all three opaque
  selectors plus visibility/enabled/action kind, spawns the resolved action, and
  returns without waiting for the action result;
- failures use stable exit categories and a bounded structured stderr record containing
  only category, entry ID when safe, and adapter exit code—never a command, environment,
  guard expression, or raw action.

Resolve action payloads only after successful validation. Shell actions execute as
`bash -lc` with the exact trusted action string; argv actions stay argv. Plugin-local
scripts must resolve below the adapter directory, reject traversal, and be executable.
All dispatched children use `start_new_session=True`, `close_fds=True`, and
`stdin/stdout/stderr=DEVNULL`, with a copied environment plus only the fixed mapping
declared by compatibility. Missing commands or scripts fail before spawn.

Write failing tests first for temporary-source end-to-end render/dispatch, malformed
source and compatibility errors, extension ownership, revision stability, stale
revision/token rejection, unknown/menu/hidden/disabled rejection, script containment,
guard descendant cleanup, provider bounds, and stderr/view-model redaction. A safe
fixture child may write a marker under a temporary directory; it must survive adapter
exit, emit arbitrarily noisy output without corrupting JSON, and prove dispatch returns
promptly. Assert the rendered stock model exposes the ten approved root categories.
No test may execute a real stock menu action.

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
shows a bounded error state. `onClose` invalidates pending callbacks.

Use a focused uncontrolled `ui.input`; changing its component key resets it when the
Clear affordance is used. Empty search shows the current menu's direct children.
Nonempty search scans the active subtree using adapter-supplied `search_text`, excludes
disabled rows, and orders direct children before deeper breadth-first matches. Because
the API has no scroll-to-index, render a stable visible window of seven or eight rows
around the selected index and show its range/total.

Keyboard behavior applies only on pressed events: Up/Down move across activatable
rows, Prior/Next move a page, Right activates, Left navigates to the parent, and input
submit activates the current (or first activatable) row. Menu/link rows navigate in
the existing model. Action rows close the panel first, then invoke exactly
`python3 <adapter> dispatch <revision> <id> <actionToken>` as argv. Dispatch callbacks
may report only a bounded category/ID/exit-code error, never payloads. This same action
path makes `apps` close this panel and open Noctalia Launcher through the adapter.

Normal browsing keeps incompatible entries visible but inert, with reduced opacity
and their adapter-provided reason. Render raw Unicode menu icons as labels, not glyph
names. Include Back, Close, Clear, Retry, loading, warnings, breadcrumb, and concise
navigation hints without depending on shell-specific components.

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
