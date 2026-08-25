package com.rokidhub.nexus.plugin.codex

data class PlannedJob(val action: String, val prompt: String, val capturePhoto: Boolean = false)

object CodexCommandPlanner {
    fun plan(text: String, hasConversation: Boolean, jobRunning: Boolean): PlannedJob {
        val normalized = text.trim().lowercase().replace('ё', 'е')
        val capturePhoto = requestsPhoto(normalized)
        projectName(normalized)?.let { return PlannedJob("select_project", it) }
        if (hasConversation && (
                normalized == "останови" || normalized.startsWith("останови ") ||
                normalized == "stop" || normalized.startsWith("stop ") || normalized == "cancel"
            )) {
            return PlannedJob("interrupt", "")
        }
        if (hasConversation && (
                normalized.contains("коротко что нашел") || normalized.contains("кратко что нашел") ||
                normalized.contains("briefly what did you find") || normalized.contains("give me a short summary") ||
                normalized.contains("summarize briefly")
            )) {
            return PlannedJob("summarize", text.trim(), capturePhoto)
        }
        if (hasConversation && (
                normalized == "продолжай" || normalized.startsWith("продолжай ") ||
                normalized == "continue" || normalized.startsWith("continue ") || normalized.startsWith("go on")
            )) {
            return PlannedJob(if (jobRunning) "steer" else "continue", text.trim(), capturePhoto)
        }
        return PlannedJob(
            if (hasConversation) "continue" else "start",
            text.trim(),
            capturePhoto = capturePhoto,
        )
    }

    private fun projectName(normalized: String): String? {
        val prefixes = listOf(
            "проект ",
            "выбери проект ",
            "открой проект ",
            "переключись на проект ",
            "переключи на проект ",
            "project ",
            "select project ",
            "open project ",
            "switch to project ",
        )
        val prefix = prefixes.firstOrNull { normalized.startsWith(it) } ?: return null
        return normalized.removePrefix(prefix).trim().trim('.', ',', '!', '?').takeIf { it.isNotBlank() }
    }

    private fun requestsPhoto(normalized: String): Boolean = listOf(
        "сделай фото",
        "сделай фотографию",
        "сфотографируй",
        "сними фото",
        "take a photo",
        "take a picture",
        "use the camera",
    ).any(normalized::contains)
}
