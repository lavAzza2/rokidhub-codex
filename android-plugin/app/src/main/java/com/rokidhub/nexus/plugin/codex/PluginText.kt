package com.rokidhub.nexus.plugin.codex

import java.util.Locale

/** Phone-locale UI for the headset. No language preference is sent to RokidHub. */
class PluginText(locale: Locale = Locale.getDefault()) {
    val isEnglish: Boolean = locale.language.lowercase() != "ru"
    val speechLocale: String = if (isEnglish) "en-US" else "ru-RU"

    fun text(russian: String, english: String): String = if (isEnglish) english else russian

    fun hudStatus(status: String, serverValue: String): String {
        if (!isEnglish) return serverValue.ifBlank { "Codex анализирует" }
        return when (status) {
            "queued", "dispatched" -> "Connecting to PC"
            "running" -> "Codex is analyzing"
            "needs_input" -> "Answer needed"
            "completed" -> "Done"
            "interrupted" -> "Stopped"
            else -> "Connecting to PC"
        }
    }
}
