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
