local cases = 0
local function check(value, message)
  if not value then error(message or "check failed", 2) end
end
local function equal(actual, expected, message)
  if actual ~= expected then
    error((message or "values differ") .. ": got " .. tostring(actual) .. ", expected " .. tostring(expected), 2)
  end
end

local renders = 0
local runs = {}
local notifications = {}
local nextRunReturns = true
local decodeValues = {}
local closed = 0
local longActionId = string.rep("long-action-id-", 8)

local function node(kind, props, children)
  return { kind = kind, props = props or {}, children = children or {} }
end

ui = {
  row = function(props, children) return node("row", props, children) end,
  column = function(props, children) return node("column", props, children) end,
  label = function(props) return node("label", props) end,
  button = function(props) return node("button", props) end,
  input = function(props) return node("input", props) end,
  spacer = function(props) return node("spacer", props) end,
}

noctalia = {
  pluginDir = function() return "/fixture/plugin" end,
  runAsync = function(argv, callback, timeout)
    if argv[3] == "dispatch" then check(closed == 1, "panel closes before dispatch spawn") end
    local item = { argv = argv, callback = callback, timeout = timeout }
    table.insert(runs, item)
    return nextRunReturns
  end,
  json = {
    decode = function(stdout)
      local value = decodeValues[stdout]
      if value == "ERROR" then error("bad json") end
      return value
    end,
  },
  notifyError = function(title, message)
    table.insert(notifications, { title = title, message = message })
  end,
}

panel = { close = function()
  closed = closed + 1
  onClose()
end }

local originalRender = nil
dofile("panel.luau")
originalRender = render
render = function()
  renders = renders + 1
  return originalRender()
end

local function fixture(revision, runLabel)
  local entries = {
    root = { id = "root", kind = "menu", label = "Go", header = "Go", parent = "", children = { "folder", "run", "disabled", "apps", "link", longActionId, "page", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12" }, visible = true, enabled = true, breadcrumb = {} },
    folder = { id = "folder", kind = "menu", label = "Folder", header = "Folder", parent = "root", children = { "deep" }, visible = true, enabled = true, searchText = "folder needle" },
    run = { id = "run", kind = "action", label = runLabel or "Run", parent = "root", children = {}, visible = true, enabled = true, actionToken = "token-run", searchText = "run needle" },
    disabled = { id = "disabled", kind = "action", label = "Disabled", parent = "root", children = {}, visible = true, enabled = false, disabled = true, disabledReason = "Unsupported provider", searchText = "disabled needle" },
    apps = { id = "apps", kind = "action", label = "Apps", parent = "root", children = {}, visible = true, enabled = true, actionToken = "token-apps", searchText = "apps" },
    link = { id = "link", kind = "link", label = "Folder link", parent = "root", target = "folder", children = {}, visible = true, enabled = true, searchText = "link" },
    [longActionId] = { id = longActionId, kind = "action", label = "Long action", parent = "root", children = {}, visible = true, enabled = true, actionToken = "token-long", searchText = "long" },
    page = { id = "page", kind = "menu", label = "Page", header = "Page", parent = "root", children = { "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12" }, visible = true, enabled = true, searchText = "page" },
    deep = { id = "deep", kind = "action", label = "Deep", parent = "folder", children = {}, visible = true, enabled = true, actionToken = "token-deep", searchText = "deep needle" },
  }
  for index = 1, 12 do
    local id = "r" .. tostring(index)
    local disabledRow = index == 5 or index == 9 or index == 12
    entries[id] = { id = id, kind = "action", label = "Row " .. tostring(index), parent = "root", children = {}, visible = true, enabled = not disabledRow, disabled = disabledRow, actionToken = "token-" .. id, searchText = "row" }
  end
  return { schemaVersion = 1, revision = revision or "rev-1", root = "root", entries = entries, warnings = { "Provider unavailable: fonts" }, source = {} }
end

local function find(tree, predicate)
  if predicate(tree) then return tree end
  for _, child in ipairs(tree.children or {}) do
    local found = find(child, predicate)
    if found then return found end
  end
  return nil
end

local function hasText(tree, text)
  return find(tree, function(item) return item.kind == "label" and item.props.text == text end) ~= nil
end

local function row(key)
  local tree = render()
  return find(tree, function(item) return item.kind == "row" and item.props.key == key end)
end

local function selectedRowKey()
  local selected = find(render(), function(item)
    return item.kind == "row" and item.props.selected == true and string.sub(item.props.key or "", 1, 4) == "row-"
  end)
  return selected and selected.props.key or ""
end

local function input()
  return find(render(), function(item) return item.kind == "input" end)
end

local function reset()
  runs = {}
  notifications = {}
  nextRunReturns = true
  decodeValues = {}
  closed = 0
  renders = 0
  onClose()
end

local function openGood()
  decodeValues.good = fixture()
  onOpen({})
  equal(#runs, 1, "render was started")
  equal(runs[1].argv[1], "python3", "render argv python")
  equal(runs[1].argv[2], "/fixture/plugin/menu_adapter.py", "render adapter path")
  equal(runs[1].argv[3], "render", "render verb")
  equal(runs[1].timeout, 10000, "render timeout")
  runs[1].callback({ exitCode = 0, stdout = "good" })
end

local function test_generation_and_last_known_good()
  reset()
  openGood()
  check(hasText(render(), "Run"), "good model rendered")
  onOpen({})
  local old = runs[1]
  local current = runs[2]
  current.callback({ exitCode = 0, stdout = "ERROR" })
  check(hasText(render(), "Run"), "bad refresh retained model")
  check(hasText(render(), "Refresh unavailable"), "bounded refresh error")
  old.callback({ exitCode = 0, stdout = "ERROR" })
  check(hasText(render(), "Run"), "old callback cannot replace model")
  cases = cases + 1
end

local function test_later_success_wins_over_older_success()
  reset()
  decodeValues.old = fixture("old-revision", "Older render")
  decodeValues.new = fixture("new-revision", "Newer render")
  onOpen({})
  onOpen({})
  runs[2].callback({ exitCode = 0, stdout = "new" })
  check(hasText(render(), "Newer render"), "newer render installed")
  runs[1].callback({ exitCode = 0, stdout = "old" })
  check(hasText(render(), "Newer render"), "older success cannot replace newer LKG")
  check(not hasText(render(), "Older render"), "older label remains absent")
  cases = cases + 1
end

local function test_rejects_bad_results_and_spawn_failure()
  reset()
  openGood()
  onOpen({})
  runs[2].callback({ exitCode = 0, stdout = "good", timedOut = true })
  check(hasText(render(), "Refresh unavailable"), "timeout rejected")
  onOpen({})
  runs[3].callback({ exitCode = 0, stdout = "good", stdoutTruncated = true })
  check(hasText(render(), "Refresh unavailable"), "truncation rejected")
  onOpen({})
  decodeValues.wrong = { schemaVersion = 2, revision = "r", root = "root", entries = { root = {} } }
  runs[4].callback({ exitCode = 0, stdout = "wrong" })
  check(hasText(render(), "Refresh unavailable"), "schema rejected")
  nextRunReturns = false
  onOpen({})
  check(hasText(render(), "Refresh unavailable"), "immediate false rejected")
  cases = cases + 1
end

local function test_close_invalidates_render_callback_without_rendering()
  reset()
  decodeValues.good = fixture()
  onOpen({})
  local beforeClose = renders
  onClose()
  equal(renders, beforeClose, "close does not render")
  runs[1].callback({ exitCode = 0, stdout = "good" })
  equal(renders, beforeClose, "closed callback does not render")
  cases = cases + 1
end

local function test_search_is_breadth_first_and_excludes_disabled()
  reset()
  openGood()
  local search = input()
  check(search.props.focus == true, "search is focused")
  search.props.onChange("needle")
  local folder = row("row-folder")
  local run = row("row-run")
  local deep = row("row-deep")
  check(folder and run and deep, "direct and deep search rows exist")
  check(row("row-disabled") == nil, "disabled search row excluded")
  local tree = render()
  local function indexOf(key)
    local count = 0
    local function walk(item)
      count = count + 1
      if item.props and item.props.key == key then return count end
      for _, child in ipairs(item.children or {}) do
        local value = walk(child)
        if value then return value end
      end
      return nil
    end
    return walk(tree)
  end
  check(indexOf("row-folder") < indexOf("row-deep"), "BFS keeps direct before deep")
  cases = cases + 1
end

local function test_clear_rekeys_input_and_window_is_eight_rows()
  reset()
  openGood()
  local before = input().props.key
  input().props.onChange("row")
  local clear = find(render(), function(item) return item.kind == "button" and item.props.text == "Clear" end)
  clear.props.onClick()
  check(input().props.key ~= before, "clear resets uncontrolled input by key")
  local count = 0
  local tree = render()
  local function walk(item)
    if item.kind == "row" and string.sub(item.props.key or "", 1, 4) == "row-" then count = count + 1 end
    for _, child in ipairs(item.children or {}) do walk(child) end
  end
  walk(tree)
  equal(count, 8, "visible row window has eight rows")
  check(find(tree, function(item) return item.kind == "label" and string.find(item.props.text or "", "/", 1, true) end), "window range shown")
  cases = cases + 1
end

local function test_keyboard_pressed_navigation_and_parent()
  reset()
  openGood()
  onKey({ key = "down", pressed = false })
  check(row("row-folder").props.selected == true, "released key ignored")
  onKey({ key = "down", pressed = true })
  check(row("row-run").props.selected == true, "down moves selection")
  onKey({ key = "up", pressed = true })
  onKey({ key = "right", pressed = true })
  check(hasText(render(), "Folder"), "right opens selected menu")
  onKey({ key = "left", pressed = true })
  check(row("row-folder") ~= nil, "left returns to parent")
  cases = cases + 1
end

local function test_keyboard_and_pointer_links_navigate_to_target()
  reset()
  openGood()
  onKey({ key = "down", pressed = true })
  onKey({ key = "down", pressed = true })
  onKey({ key = "down", pressed = true })
  onKey({ key = "right", pressed = true })
  check(row("row-deep") ~= nil, "keyboard right follows link target")
  reset()
  openGood()
  row("row-link").props.onClick()
  check(row("row-deep") ~= nil, "pointer follows link target")
  cases = cases + 1
end

local function test_page_navigation_clamps_and_skips_disabled_landing_rows()
  reset()
  openGood()
  row("row-page").props.onClick()
  equal(selectedRowKey(), "row-r1", "page starts at first activatable row")
  onKey({ key = "next", pressed = true })
  equal(selectedRowKey(), "row-r10", "next skips disabled r9 in requested direction")
  onKey({ key = "next", pressed = true })
  equal(selectedRowKey(), "row-r11", "next clamps then searches back from disabled edge")
  onKey({ key = "next", pressed = true })
  equal(selectedRowKey(), "row-r11", "next may remain at clamped disabled edge")
  onKey({ key = "prior", pressed = true })
  equal(selectedRowKey(), "row-r3", "prior uses non-cyclic page target")
  onKey({ key = "prior", pressed = true })
  equal(selectedRowKey(), "row-r1", "prior clamps at first row")
  onKey({ key = "prior", pressed = true })
  equal(selectedRowKey(), "row-r1", "prior remains at first edge")
  cases = cases + 1
end

local function test_disabled_rows_are_inert_but_visible()
  reset()
  openGood()
  local disabled = row("row-disabled")
  check(disabled ~= nil, "disabled normal row visible")
  check(disabled.props.onClick == nil, "disabled compound row has no handler")
  equal(disabled.props.opacity, 0.5, "disabled row opacity")
  check(hasText(render(), "Unsupported provider"), "disabled reason shown")
  cases = cases + 1
end

local function test_pointer_dispatch_closes_first_and_is_exact_argv()
  reset()
  openGood()
  local run = row("row-run")
  run.props.onClick()
  equal(closed, 1, "action closes panel first")
  equal(#runs, 2, "dispatch started")
  local argv = runs[2].argv
  equal(argv[1], "python3", "dispatch python")
  equal(argv[2], "/fixture/plugin/menu_adapter.py", "dispatch adapter")
  equal(argv[3], "dispatch", "dispatch verb")
  equal(argv[4], "rev-1", "dispatch revision")
  equal(argv[5], "run", "dispatch id")
  equal(argv[6], "token-run", "dispatch opaque token")
  runs[2].callback({ exitCode = 7, stdout = "SECRET_STDOUT", stderr = "SECRET_STDERR" })
  equal(#notifications, 1, "dispatch failure notified")
  for _, secret in ipairs({ "SECRET_STDOUT", "SECRET_STDERR", "rev-1", "token-run", "payload" }) do
    check(not string.find(notifications[1].message, secret, 1, true), "dispatch error redacts " .. secret)
  end
  check(string.find(notifications[1].message, "run", 1, true), "bounded ID included")
  cases = cases + 1
end

local function test_long_ids_dispatch_unchanged_but_notifications_are_bounded()
  reset()
  openGood()
  row("row-" .. longActionId).props.onClick()
  equal(runs[2].argv[5], longActionId, "pointer keeps complete long adapter ID")
  runs[2].callback({ exitCode = 9, stdout = "RAW", stderr = "RAW" })
  equal(notifications[1].message, "Action failed: selection (exit 9)", "long ID notification is bounded")
  reset()
  openGood()
  input().props.onChange("long")
  input().props.onSubmit("long")
  equal(runs[2].argv[5], longActionId, "submit keeps complete long adapter ID")
  reset()
  openGood()
  nextRunReturns = false
  row("row-run").props.onClick()
  equal(notifications[1].message, "Action failed: run", "immediate false uses fixed redacted error")
  cases = cases + 1
end

local function test_submit_uses_selected_row_and_retry_starts_new_generation()
  reset()
  openGood()
  onKey({ key = "down", pressed = true })
  input().props.onSubmit("anything")
  equal(closed, 1, "submit activates current selection")
  reset()
  openGood()
  onOpen({})
  runs[2].callback({ exitCode = 1, stdout = "" })
  local retry = find(render(), function(item) return item.kind == "button" and item.props.text == "Retry" end)
  retry.props.onClick()
  equal(#runs, 3, "retry starts a new render generation")
  cases = cases + 1
end

test_generation_and_last_known_good()
test_later_success_wins_over_older_success()
test_rejects_bad_results_and_spawn_failure()
test_close_invalidates_render_callback_without_rendering()
test_search_is_breadth_first_and_excludes_disabled()
test_clear_rekeys_input_and_window_is_eight_rows()
test_keyboard_pressed_navigation_and_parent()
test_keyboard_and_pointer_links_navigate_to_target()
test_page_navigation_clamps_and_skips_disabled_landing_rows()
test_disabled_rows_are_inert_but_visible()
test_pointer_dispatch_closes_first_and_is_exact_argv()
test_long_ids_dispatch_unchanged_but_notifications_are_bounded()
test_submit_uses_selected_row_and_retry_starts_new_generation()

equal(cases, 13, "case count")
print("panel harness: 13 passed")
