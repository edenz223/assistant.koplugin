local helper = require("test.helper")
local assert = helper.assert
local SentenceContext = require("assistant_sentence_context")

-- Load the real dialog methods without constructing any widgets.
local saved = {}
local stubs = { "ui/widget/horizontalgroup", "ui/widget/horizontalspan",
    "ui/widget/verticalspan", "ui/widget/linewidget", "ui/trapper",
    "assistant_viewer", "assistant_notebook" }
for i, name in ipairs(stubs) do
    saved[name] = package.loaded[name]
    package.loaded[name] = {}
end
local project_root = debug.getinfo(1).source:sub(2):gsub("\\", "/"):match("^(.*)/test/") or "."
local Dialog = dofile(project_root .. "/assistant_dialog.lua")
for i, name in ipairs(stubs) do package.loaded[name] = saved[name] end

local function selection(previous, word, following)
    return { highlight = {
        selected_text = { text = word },
        getSelectedWordContext = function() return previous, following end,
    } }
end

local tests = {
    { name = "short sentence excludes neighbors and keeps repeated occurrence", fn = function()
        assert.equal(SentenceContext.extract(selection("Word was earlier. This ", "word", " matters. Next sentence."), "word"), "Word was earlier. This word matters.")
    end },
    { name = "CJK boundaries and closing quotes", fn = function()
        assert.equal(SentenceContext.extract(selection("上一句。「这是", "苹果", "。」下一句。"), "苹果"), "上一句。「这是苹果。」")
    end },
    { name = "selection includes terminal punctuation", fn = function()
        assert.equal(SentenceContext.extract(selection("Before. Say ", "hello!", " Next."), "hello!"), "Before. Say hello!")
    end },
    { name = "decimal is not a sentence boundary", fn = function()
        assert.equal(SentenceContext.extract(selection("Before. It costs 3.14 ", "dollars", ". Next."), "dollars"), "Before. It costs 3.14 dollars.")
    end },
    { name = "unpunctuated document edges and short sentence", fn = function()
        assert.equal(SentenceContext.extract(selection("", "Hi", "! Next."), "Hi"), "Hi!")
        assert.equal(SentenceContext.extract(selection("Just ", "one", " line"), "one"), "Just one line")
    end },
    { name = "long sentence expands beyond initial word window", fn = function()
        local calls = 0
        local ui = selection("", "word", "")
        ui.highlight.getSelectedWordContext = function(self, count)
            calls = calls + 1
            if count == 32 then return "partial ", " partial" end
            return "Previous. A long sentence with ", " inside it. Next."
        end
        assert.equal(SentenceContext.extract(ui, "word"), "Previous. A long sentence with word inside it.")
        assert.equal(calls, 3)
    end },
    { name = "unavailable and stale selections never attach unrelated text", fn = function()
        assert.equal(SentenceContext.extract({}, "word"), "word")
        assert.equal(SentenceContext.extract(selection("Other ", "selection", "."), "word"), "word")
        local ui = selection("", "word", "")
        ui.highlight.getSelectedWordContext = function() error("unsupported") end
        assert.equal(SentenceContext.extract(ui, "word"), "word")
    end },
    { name = "extraction limit does not send a raw context window", fn = function()
        local ui = selection("", "word", "")
        ui.highlight.getSelectedWordContext = function(self, count)
            return string.rep("before ", count), string.rep(" after", count)
        end
        assert.equal(SentenceContext.extract(ui, "word"), "word")
    end },
    { name = "sentence context overrides book settings and removes prior broad history", fn = function()
        local dialog = Dialog:new({ ui = selection("Before. This ", "word", " matters. After."),
            settings = { readSetting = function() error("must not read book context switches") end } })
        dialog._buildBookContextMessage = function() error("must not extract pages") end
        local history = { { role = "system", content = "Instructions" },
            { role = "user", content = "Whole book" }, { role = "assistant", content = "Earlier reply" } }
        dialog:_appendPromptContext(history, "word", { use_sentence_context = true, use_book_context = true })
        assert.equal(#history, 2)
        assert.equal(history[1].content, "Instructions")
        assert.matches(history[2].content, "Before%. This word matters%.")
        assert.equal(helper.ASUtils.get_attr(history[2], "is_context"), true)
        dialog.assistant.ui.highlight = nil
        dialog:_appendPromptContext(history, "word", { use_sentence_context = true })
        assert.matches(history[2].content, "Before%. This word matters%.")
    end },
    { name = "existing book context behavior remains available", fn = function()
        local dialog = Dialog:new({ settings = { readSetting = function() return true end } })
        dialog._buildBookContextMessage = function() return { role = "user", content = "Book context" } end
        local history = { { role = "system", content = "Instructions" } }
        dialog:_appendPromptContext(history, "word", { use_book_context = true })
        assert.equal(history[2].content, "Book context")
        dialog:_appendPromptContext(history, "word", {})
        assert.equal(#history, 2)
    end },
    { name = "runPrompt sends sentence-only payload and refreshes repeated lookups", fn = function()
        local prompts = require("assistant_prompts")
        local original = {}
        local replacements = {
            getMergedPrompts = function() return { lookup = {
                text = "Lookup", user_prompt = "Explain {highlight}", system_prompt = "Instructions",
                use_sentence_context = true, use_book_context = true,
            } } end,
            getDisplayText = function(title) return title end,
            isWebSearchEnabled = function() return false end,
            isSuggestionsEnabled = function() return false end,
        }
        for key, value in pairs(replacements) do original[key] = prompts[key]; prompts[key] = value end
        local ok, err = pcall(function()
            local captured
            local assistant = {
                ui = selection("Before. First ", "word", " here. After."),
                config = { getFeature = function() return {} end },
                querier = { query = function(self, history) captured = history; return "Answer" end },
            }
            local dialog = Dialog:new(assistant)
            dialog._formatUserPrompt = function(self, template, word) return "Explain " .. word end
            dialog._showResultViewer = function() end
            dialog._buildBookContextMessage = function() error("unexpected book context") end
            dialog:runPrompt("word", "lookup", "")
            assert.equal(captured[1].content, "Instructions")
            assert.matches(captured[2].content, "Before%. First word here%.")
            assert.equal(captured[3].content, "Explain word")
            assert.equal(#captured, 4) -- system, sentence, task, returned answer
            assistant.ui = selection("Earlier. Second ", "word", " there. Later.")
            dialog:runPrompt("word", "lookup", "")
            assert.matches(captured[2].content, "Earlier%. Second word there%.")
            assert.notMatches(captured[2].content, "First")
        end)
        for key in pairs(replacements) do prompts[key] = original[key] end
        if not ok then error(err) end
    end },
}

return helper.runTests("sentence_context", tests)
