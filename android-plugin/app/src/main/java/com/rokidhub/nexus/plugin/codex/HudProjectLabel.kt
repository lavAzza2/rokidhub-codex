package com.rokidhub.nexus.plugin.codex

object HudProjectLabel {
    fun normalize(value: String?): String? {
        val clean = value.orEmpty().trim().replace(Regex("\\s+"), " ")
        return clean.take(48).takeIf { it.isNotBlank() && '/' !in it && '\\' !in it }
    }

    fun footer(projectName: String?, hint: String?): String? {
        val project = normalize(projectName)?.let { "Проект: $it" }
        val cleanHint = hint?.trim()?.take(72)?.takeIf(String::isNotBlank)
        return listOfNotNull(project, cleanHint).joinToString("  ·  ").take(112).takeIf(String::isNotBlank)
    }
}
