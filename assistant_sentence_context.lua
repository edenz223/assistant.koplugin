-- Selection-anchored sentence context. Never search for the first occurrence of
-- a word: repeated words must resolve to the occurrence the reader selected.
local util = require("util")
local M = {}
local endings = { ["."] = true, ["!"] = true, ["?"] = true,
    ["。"] = true, ["！"] = true, ["？"] = true, ["…"] = true }
local closers = { ['"'] = true, ["'"] = true, [")"] = true, ["]"] = true,
    ["”"] = true, ["’"] = true, ["」"] = true, ["』"] = true, ["）"] = true }

local function normalize(text)
    return (text or ""):gsub("%s+", " "):match("^%s*(.-)%s*$")
end

-- Returns the selected sentence and its preceding sentence, plus whether the
-- previous sentence and selected sentence boundaries are complete.
function M.clip(previous, selected, following)
    local text = previous .. selected .. following
    local first, last = #previous + 1, #previous + #selected
    local boundaries = {}
    local byte_pos, boundary = 1, nil
    for char in text:gmatch(util.UTF8_CHAR_PATTERN) do
        local char_end = byte_pos + #char - 1
        -- A decimal point is not a sentence ending.
        local decimal = char == "." and text:sub(byte_pos - 1, byte_pos - 1):match("%d")
            and text:sub(char_end + 1, char_end + 1):match("%d")
        if endings[char] and not decimal then
            boundary = char_end
        elseif boundary and closers[char] then
            boundary = char_end
        else
            if boundary then boundaries[#boundaries + 1] = boundary end
            boundary = nil
        end
        byte_pos = char_end + 1
    end
    if boundary then boundaries[#boundaries + 1] = boundary end

    local current_start, current_end, current_start_index, current_end_index = 1, #text, 0, nil
    local selection_ends_sentence = selected:match("[.!?。！？…][\"'”’」』）%)%]%}]*%s*$") ~= nil
    for i, position in ipairs(boundaries) do
        if position < first then
            current_start = position + 1
            current_start_index = i
        elseif (position >= last or (selection_ends_sentence and position < last)) and not current_end_index then
            current_end = position
            current_end_index = i
        end
    end

    -- Start at the boundary before the previous sentence and end at the
    -- selected sentence boundary. Do not include the following sentence.
    local previous_start = current_start_index > 1 and boundaries[current_start_index - 1] or nil
    local range_start = previous_start and previous_start + 1 or 1
    local range_end = current_end_index and boundaries[current_end_index] or #text
    local previous_complete = current_start_index > 1 or previous == ""
    local current_complete = current_end_index ~= nil or following == ""
    return text:sub(range_start, range_end):match("^%s*(.-)%s*$"), previous_complete, current_complete
end

function M.extract(ui, highlighted_text)
    local highlight = ui and ui.highlight
    local selection = highlight and highlight.selected_text
    if not selection or not selection.text or not highlight.getSelectedWordContext
        or normalize(selection.text) ~= normalize(highlighted_text) then
        return highlighted_text or ""
    end
    local old_previous, old_following
    -- Expand until the previous and selected sentences are complete, or the
    -- document edges are reached.
    -- The cap protects the UI against unpunctuated documents; it never causes
    -- the raw word window to be sent as a substitute for sentence context.
    for i, count in ipairs({ 32, 64, 128, 256, 512, 1024 }) do
        local ok, previous, following = pcall(highlight.getSelectedWordContext, highlight, count)
        if not ok or type(previous) ~= "string" or type(following) ~= "string" then
            return highlighted_text or ""
        end
        local sentence, has_start, has_end = M.clip(previous, selection.text, following)
        local previous_complete = has_start or previous == "" or previous == old_previous
        local current_complete = has_end or following == "" or following == old_following
        if previous_complete and current_complete then return sentence end
        old_previous, old_following = previous, following
    end
    return highlighted_text or ""
end

return M
