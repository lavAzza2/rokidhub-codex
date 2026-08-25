package com.rokidhub.nexus.plugin.codex

import org.junit.Assert.assertEquals
import org.junit.Test

class CodexCommandPlannerTest {
    @Test fun newRequestStartsConversation() = assertEquals("start", CodexCommandPlanner.plan("Проверь проект", false, false).action)
    @Test fun continueSteersRunningTurn() = assertEquals("steer", CodexCommandPlanner.plan("Продолжай короче", true, true).action)
    @Test fun continueCreatesTurnWhenIdle() = assertEquals("continue", CodexCommandPlanner.plan("Продолжай", true, false).action)
    @Test fun stopInterruptsConversation() = assertEquals("interrupt", CodexCommandPlanner.plan("Останови", true, true).action)
    @Test fun shortSummaryUsesSummarize() = assertEquals("summarize", CodexCommandPlanner.plan("Коротко что нашёл?", true, false).action)
    @Test fun englishContinueSteersRunningTurn() = assertEquals("steer", CodexCommandPlanner.plan("Continue but be concise", true, true).action)
    @Test fun englishStopInterruptsConversation() = assertEquals("interrupt", CodexCommandPlanner.plan("Stop", true, true).action)
    @Test fun englishSummaryUsesSummarize() = assertEquals("summarize", CodexCommandPlanner.plan("Briefly what did you find?", true, false).action)
    @Test fun voiceCanSelectProject() {
        val planned = CodexCommandPlanner.plan("Выбери проект Рокид", true, false)
        assertEquals("select_project", planned.action)
        assertEquals("рокид", planned.prompt)
    }

    @Test fun shortVoiceCommandCanSelectProject() {
        val planned = CodexCommandPlanner.plan("Проект RokidCodex", true, false)
        assertEquals("select_project", planned.action)
        assertEquals("rokidcodex", planned.prompt)
    }

    @Test fun englishVoiceCanSelectProject() {
        val planned = CodexCommandPlanner.plan("Select project Rokid", true, false)
        assertEquals("select_project", planned.action)
        assertEquals("rokid", planned.prompt)
    }
}
