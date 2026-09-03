--!nonstrict
-- A retained Noctalia panel. The adapter owns all source parsing and dispatch
-- validation; this file only renders its redacted view model and passes opaque
-- selectors back across the process boundary.

local WINDOW_SIZE = 8
local RENDER_TIMEOUT_MS = 10000
local DISPATCH_TIMEOUT_MS = 10000
local CACHE_FILENAME = "menu-cache-v1.json"
local MAX_CACHE_BYTES = 2 * 1024 * 1024

local generation = 0
local open = false
local loading = false
local model = nil
local lastGood = nil
local refreshError = ""
local currentId = ""
local selectedId = ""
local query = ""
local inputRevision = 0
local cacheLoaded = false

local function adapterPath()
  return noctalia.pluginDir() .. "/menu_adapter.py"
end

local function stringValue(value)
  if type(value) == "string" then return value end
  return ""
end

local function tableValue(value)
  if type(value) == "table" then return value end
  return nil
end

local function entryFor(id)
  if model == nil then return nil end
  local entries = tableValue(model.entries)
  if entries == nil then return nil end
  return tableValue(entries[id])
end

local function modelIsValid(value)
  if type(value) ~= "table" or value.schemaVersion ~= 1 then return false end
  if type(value.revision) ~= "string" or value.revision == "" then return false end
  if type(value.root) ~= "string" or value.root == "" then return false end
  if type(value.entries) ~= "table" then return false end
  return type(value.entries[value.root]) == "table"
end

local function cachePath()
  local ok, directory = pcall(noctalia.pluginDataDir)
  if not ok or type(directory) ~= "string" or directory == "" then return nil end
  return directory .. "/" .. CACHE_FILENAME
end

local function restoreCache()
  if cacheLoaded then return end
  cacheLoaded = true
  local path = cachePath()
  if path == nil then return end
  local readOk, raw = pcall(noctalia.readFile, path)
  if not readOk or type(raw) ~= "string" or raw == "" or #raw > MAX_CACHE_BYTES then return end
  local decodeOk, decoded = pcall(noctalia.json.decode, raw)
  if not decodeOk or not modelIsValid(decoded) then return end
  model = decoded
  lastGood = decoded
end

local function persistCache(raw)
  if type(raw) ~= "string" or raw == "" or #raw > MAX_CACHE_BYTES then return end
  local path = cachePath()
  if path == nil then return end
  local staging = path .. ".tmp"
  local writeOk, wrote = pcall(noctalia.writeFile, staging, raw)
  if not writeOk or wrote == false then return end
  pcall(noctalia.renameFile, staging, path)
end

local function isVisible(entry)
  return entry ~= nil and entry.visible ~= false
end

local function isDisabled(entry)
  return entry == nil or entry.enabled ~= true or entry.disabled == true
end

local function isActivatable(entry)
  if not isVisible(entry) or isDisabled(entry) then return false end
  local kind = stringValue(entry.kind)
  if kind == "menu" then return true end
  if kind == "link" then return entryFor(stringValue(entry.target)) ~= nil end
  return kind == "action" and stringValue(entry.actionToken) ~= ""
end

local function childIds(entry)
  local children = entry and tableValue(entry.children)
  if children == nil then return {} end
  return children
end

local function rowsForCurrent()
  local current = entryFor(currentId)
  if current == nil then return {} end
  local rows = {}
  local needle = string.lower(query):gsub("^%s+", ""):gsub("%s+$", "")
  if needle == "" then
    for _, id in ipairs(childIds(current)) do
      local entry = entryFor(id)
      if isVisible(entry) then table.insert(rows, id) end
    end
    return rows
  end

  local queue = {}
  for _, id in ipairs(childIds(current)) do table.insert(queue, id) end
  local cursor = 1
  while cursor <= #queue do
    local id = queue[cursor]
    cursor = cursor + 1
    local entry = entryFor(id)
    if isVisible(entry) then
      for _, child in ipairs(childIds(entry)) do table.insert(queue, child) end
      local searchText = string.lower(stringValue(entry.searchText))
      if not isDisabled(entry) and string.find(searchText, needle, 1, true) then
        table.insert(rows, id)
      end
    end
  end
  return rows
end

local function selectedIndex(rows)
  for index, id in ipairs(rows) do
    if id == selectedId then return index end
  end
  return nil
end

local function ensureSelection(rows)
  local selected = selectedIndex(rows)
  if selected ~= nil and isActivatable(entryFor(selectedId)) then return selected end
  for index, id in ipairs(rows) do
    if isActivatable(entryFor(id)) then
      selectedId = id
      return index
    end
  end
  selectedId = ""
  return nil
end

local function visibleWindow(rows, selected)
  local total = #rows
  if total == 0 then return {}, 0, 0 end
  local start = 1
  if selected ~= nil then
    start = selected - math.floor((WINDOW_SIZE - 1) / 2)
  end
  local lastStart = math.max(1, total - WINDOW_SIZE + 1)
  start = math.max(1, math.min(start, lastStart))
  local finish = math.min(total, start + WINDOW_SIZE - 1)
  local window = {}
  for index = start, finish do table.insert(window, rows[index]) end
  return window, start, finish
end

local function notificationId(value)
  local id = stringValue(value)
  if id == "" or #id > 96 or not string.match(id, "^[%w_.:-]+$") then return "selection" end
  return id
end

local function dispatch(entry, entryId)
  if model == nil or not isActivatable(entry) or stringValue(entry.kind) ~= "action" then return end
  local revision = stringValue(model.revision)
  local id = stringValue(entryId)
  local token = stringValue(entry.actionToken)
  if revision == "" or token == "" or id == "" then return end
  local displayId = notificationId(id)

  -- The host owns onClose; invoking close before creating the process prevents a
  -- dispatched action from changing the still-visible retained tree.
  panel.close()
  local started = noctalia.runAsync(
    { "python3", adapterPath(), "dispatch", revision, id, token },
    function(result)
      if result == nil or result.timedOut == true or result.exitCode ~= 0 then
        local code = result and tonumber(result.exitCode) or nil
        local suffix = code and (" (exit " .. tostring(code) .. ")") or ""
        noctalia.notifyError("Omarchy Menu", "Action failed: " .. displayId .. suffix)
      end
    end,
    DISPATCH_TIMEOUT_MS
  )
  if started == false then
    noctalia.notifyError("Omarchy Menu", "Action failed: " .. displayId)
  end
end

local function activate(id)
  local entry = entryFor(id)
  if not isActivatable(entry) then return end
  local kind = stringValue(entry.kind)
  if kind == "menu" then
    currentId = stringValue(entry.id)
    selectedId = ""
    ensureSelection(rowsForCurrent())
    render()
  elseif kind == "link" then
    currentId = stringValue(entry.target)
    selectedId = ""
    ensureSelection(rowsForCurrent())
    render()
  else
    dispatch(entry, id)
  end
end

local function failRefresh()
  loading = false
  if lastGood ~= nil then model = lastGood end
  refreshError = "Refresh unavailable"
  noctalia.notifyError("Omarchy Menu", refreshError)
  if open then render() end
end

local function refresh()
  if not open then return end
  generation = generation + 1
  local requestGeneration = generation
  loading = true
  refreshError = ""
  render()
  local started = noctalia.runAsync(
    { "python3", adapterPath(), "render" },
    function(result)
      if requestGeneration ~= generation then return end
      if result == nil or result.timedOut == true or result.stdoutTruncated == true
        or result.stderrTruncated == true or result.exitCode ~= 0 or type(result.stdout) ~= "string" then
        if open then failRefresh() else loading = false end
        return
      end
      local ok, decoded = pcall(noctalia.json.decode, result.stdout)
      if not ok or not modelIsValid(decoded) then
        if open then failRefresh() else loading = false end
        return
      end
      model = decoded
      lastGood = decoded
      persistCache(result.stdout)
      loading = false
      refreshError = ""
      if not open then return end
      if entryFor(currentId) == nil then currentId = stringValue(model.root) end
      ensureSelection(rowsForCurrent())
      render()
    end,
    RENDER_TIMEOUT_MS
  )
  if started == false and open and requestGeneration == generation then failRefresh() end
end

local function navigateParent()
  local current = entryFor(currentId)
  local parent = current and stringValue(current.parent) or ""
  if parent ~= "" and entryFor(parent) ~= nil then
    currentId = parent
    selectedId = ""
    ensureSelection(rowsForCurrent())
    render()
  end
end

local function moveSelection(delta)
  local rows = rowsForCurrent()
  local selected = ensureSelection(rows)
  if selected == nil then return end
  local index = selected
  for _ = 1, #rows do
    index = ((index - 1 + delta) % #rows) + 1
    if isActivatable(entryFor(rows[index])) then
      selectedId = rows[index]
      render()
      return
    end
  end
end

local function movePage(delta)
  local rows = rowsForCurrent()
  local selected = ensureSelection(rows)
  if selected == nil then return end
  local target = math.max(1, math.min(#rows, selected + delta))
  local direction = delta < 0 and -1 or 1
  local function selectFrom(index, step)
    while index >= 1 and index <= #rows do
      if isActivatable(entryFor(rows[index])) then
        selectedId = rows[index]
        render()
        return true
      end
      index = index + step
    end
    return false
  end
  if not selectFrom(target, direction) then
    selectFrom(target - direction, -direction)
  end
end

local function breadcrumb()
  local current = entryFor(currentId)
  if current == nil then return "Go" end
  local parts = tableValue(current.breadcrumb) or {}
  if #parts == 0 then return stringValue(current.header) ~= "" and stringValue(current.header) or "Go" end
  return table.concat(parts, " / ")
end

local function rowNode(id)
  local entry = entryFor(id)
  if entry == nil then return ui.row({ key = "row-missing" }, {}) end
  local icon = stringValue(entry.icon)
  local label = stringValue(entry.label)
  local title = icon ~= "" and (icon .. " " .. label) or label
  local selected = id == selectedId
  local props = {
    key = "row-" .. id,
    gap = 10,
    align = "center",
    paddingH = 10,
    paddingV = 8,
    radius = 8,
    fill = selected and "primary/0.10" or "surface_variant/0.20",
    border = selected and "primary/0.55" or "outline/0.10",
    borderWidth = 1,
  }
  if not isActivatable(entry) then props.opacity = 0.5 else props.onClick = function() activate(id) end end
  local text = {
    ui.label({ text = title, color = selected and "primary" or "on_surface", maxLines = 1 }),
  }
  local reason = stringValue(entry.disabledReason)
  if reason ~= "" then table.insert(text, ui.label({ text = reason, fontSize = 10, color = "on_surface_variant", maxLines = 1 })) end
  local children = { ui.column({ gap = 1, flexGrow = 1 }, text) }
  if entry.checked == true then table.insert(children, ui.label({ text = "✓", color = "primary" })) end
  local kind = stringValue(entry.kind)
  if kind == "menu" or kind == "link" then
    table.insert(children, ui.label({ text = "›", fontSize = 18, color = "on_surface_variant" }))
  end
  return ui.row(props, children)
end

render = function()
  local rows = rowsForCurrent()
  local selected = ensureSelection(rows)
  local window, first, last = visibleWindow(rows, selected)
  local current = entryFor(currentId)
  local parent = current and stringValue(current.parent) or ""
  local header = {
    ui.column({ key = "heading", gap = 0, flexGrow = 1 }, {
      ui.label({ text = "Omarchy Menu", fontSize = 18, fontWeight = "bold", color = "on_surface" }),
      ui.label({ text = breadcrumb(), fontSize = 11, color = "on_surface_variant", maxLines = 1 }),
    }),
  }
  if parent ~= "" and entryFor(parent) ~= nil then
    table.insert(header, ui.button({ key = "back", glyph = "arrow-left", variant = "ghost", tooltip = "Back", onClick = navigateParent }))
  end
  table.insert(header, ui.button({ key = "close", glyph = "close", variant = "ghost", tooltip = "Close", onClick = function() panel.close() end }))
  local body = {
    ui.row({ key = "header", gap = 8, align = "center" }, header),
    ui.row({ key = "search-row", gap = 6, align = "center" }, {
      ui.input({
        key = "search-" .. tostring(inputRevision),
        focus = true,
        placeholder = "Search menu",
        flexGrow = 1,
        onChange = function(value)
          query = stringValue(value)
          ensureSelection(rowsForCurrent())
          render()
        end,
        onSubmit = function(_value)
          local currentRows = rowsForCurrent()
          local selectedNow = ensureSelection(currentRows)
          if selectedNow ~= nil then activate(currentRows[selectedNow]) end
        end,
      }),
      ui.button({ text = "Clear", variant = "ghost", onClick = function()
        query = ""
        inputRevision = inputRevision + 1
        ensureSelection(rowsForCurrent())
        render()
      end }),
    }),
  }
  if refreshError ~= "" then
    table.insert(body, ui.row({ key = "refresh-error", gap = 8, align = "center" }, {
      ui.label({ text = refreshError, color = "error", flexGrow = 1 }),
      ui.button({ text = "Retry", variant = "ghost", onClick = refresh }),
    }))
  end
  if model ~= nil then
    local warnings = tableValue(model.warnings) or {}
    for _, warning in ipairs(warnings) do
      if type(warning) == "string" then table.insert(body, ui.label({ text = "Warning: " .. warning, fontSize = 11, color = "on_surface_variant" })) end
    end
  end
  local list = {}
  if #rows == 0 then
    table.insert(list, ui.label({
      text = loading and model == nil and "Loading menu…" or "No matching menu items",
      color = "on_surface_variant",
      flexGrow = 1,
      textAlign = "center",
    }))
  else
    for _, id in ipairs(window) do table.insert(list, rowNode(id)) end
    table.insert(list, ui.spacer({ key = "list-spacer", flexGrow = 1 }))
    table.insert(list, ui.row({ key = "page-status", justify = "center" }, {
      ui.label({ text = tostring(first) .. "–" .. tostring(last) .. " of " .. tostring(#rows), fontSize = 10, color = "on_surface_variant", textAlign = "center" }),
    }))
  end
  table.insert(body, ui.column({ key = "menu-body", flexGrow = 1, gap = 5, align = "stretch" }, list))
  table.insert(body, ui.row({ key = "footer", justify = "center", align = "center" }, {
    ui.label({ text = "↑↓ Navigate   PgUp/PgDn Page   ← Back   → Open", fontSize = 10, color = "on_surface_variant", textAlign = "center" }),
  }))
  local tree = ui.column({ key = "menu-root", flexGrow = 1, gap = 10, align = "stretch" }, body)
  panel.render(tree)
  return tree
end

function onOpen(_context)
  open = true
  query = ""
  inputRevision = inputRevision + 1
  restoreCache()
  if model ~= nil and type(model.root) == "string" then currentId = model.root end
  selectedId = ""
  refresh()
end

function onClose()
  open = false
  loading = false
end

function onKey(chord, pressed)
  if type(chord) ~= "string" or pressed ~= true then return end
  local key = string.lower(chord)
  if key == "up" then moveSelection(-1)
  elseif key == "down" then moveSelection(1)
  elseif key == "prior" or key == "pageup" or key == "pgup" then movePage(-WINDOW_SIZE)
  elseif key == "next" or key == "pagedown" or key == "pgdn" then movePage(WINDOW_SIZE)
  elseif key == "left" then navigateParent()
  elseif key == "right" then
    local rows = rowsForCurrent()
    local selected = ensureSelection(rows)
    if selected ~= nil then activate(rows[selected]) end
  end
end
