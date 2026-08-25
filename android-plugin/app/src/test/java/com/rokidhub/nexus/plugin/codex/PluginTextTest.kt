package com.rokidhub.nexus.plugin.codex

import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PluginTextTest {
    @Test fun russianPhoneUsesRussianSpeech() {
        val text = PluginText(Locale.forLanguageTag("ru-RU"))
        assertFalse(text.isEnglish)
        assertEquals("ru-RU", text.speechLocale)
        assertEquals("Готово", text.text("Готово", "Done"))
    }

    @Test fun nonRussianPhoneUsesEnglishSpeechAndHud() {
        val text = PluginText(Locale.forLanguageTag("en-US"))
        assertTrue(text.isEnglish)
        assertEquals("en-US", text.speechLocale)
        assertEquals("Codex is analyzing", text.hudStatus("running", "Codex анализирует"))
    }
}
