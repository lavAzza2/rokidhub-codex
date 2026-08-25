package com.rokidhub.nexus.plugin.codex

import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import com.anezium.rokidbus.client.plugin.NexusCard
import com.anezium.rokidbus.client.plugin.NexusPluginService
import com.anezium.rokidbus.client.plugin.NexusSdkResult
import com.anezium.rokidbus.client.plugin.NexusSpeechCallbacks
import com.anezium.rokidbus.client.plugin.NexusSpeechError
import com.anezium.rokidbus.client.plugin.NexusSpeechSession
import com.anezium.rokidbus.client.plugin.NexusSpeechState
import com.anezium.rokidbus.client.plugin.NexusSpeechStopReason
import com.anezium.rokidbus.client.plugin.NexusSurfaceSession
import com.anezium.rokidbus.client.plugin.NexusTtsCallbacks
import com.anezium.rokidbus.client.plugin.NexusTtsDoneReason
import com.anezium.rokidbus.client.plugin.NexusTtsSession
import com.anezium.rokidbus.shared.plugin.NexusInputEvent

class RokidHubCodexPluginService : NexusPluginService() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var credentials: CredentialStore
    private lateinit var ui: PluginText
    private val api = CodexApi()
    private var surface: NexusSurfaceSession? = null
    private var speech: NexusSpeechSession? = null
    private var tts: NexusTtsSession? = null
    private var surfaceShown = false
    private var generation = 0
    private var submittedFinal = false
    private var currentJobId: String? = null
    private var jobRunning = false

    override fun onCreate() {
        super.onCreate()
        credentials = CredentialStore(applicationContext)
        ui = PluginText()
    }

    override fun onNexusOpen() {
        generation += 1
        surface = nexusSurfaceSession(SURFACE_ID)
        surfaceShown = false
        val current = generation
        if (credentials.readAccessToken() == null) beginPairing(current) else checkDesktopAndListen(current)
    }

    override fun onNexusClose() {
        generation += 1
        main.removeCallbacksAndMessages(null)
        speech?.stop()
        speech = null
        tts?.close()
        tts = null
        surface = null
        surfaceShown = false
    }

    override fun onDestroy() {
        api.close()
        super.onDestroy()
    }

    override fun onNexusInput(event: NexusInputEvent) {
        if (event.action != KeyEvent.ACTION_DOWN) return
        when (event.keyCode) {
            KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER -> if (speech == null) {
                if (credentials.readAccessToken() == null) beginPairing(generation) else beginListening(generation)
            }
            KeyEvent.KEYCODE_BACK -> surface?.hide()
        }
    }

    private fun beginPairing(current: Int) {
        show(
            ui.text("Подключение", "Connecting"),
            listOf(ui.text("Создаю одноразовый код…", "Creating a one-time code…")),
            ui.text("Код действует 10 минут", "The code is valid for 10 minutes"),
        )
        api.startPairing(credentials.installationId) { result ->
            main.post {
                if (current != generation) return@post
                val response = result.getOrNull()
                if (response?.successful != true) {
                    show(
                        ui.text("Нет связи с RokidHub", "RokidHub is unavailable"),
                        listOf(response?.message() ?: ui.text("Проверь интернет на телефоне.", "Check the phone's internet connection.")),
                        ui.text("Нажми, чтобы повторить", "Press to try again"),
                    )
                    return@post
                }
                val code = response.payload.optString("code")
                val pollSecret = response.payload.optString("poll_secret")
                show(
                    ui.text("Привяжи Codex", "Pair Codex"),
                    listOf(ui.text("Открой rokidhub.com и войди", "Open rokidhub.com and sign in"), ui.text("Введи код: $code", "Enter code: $code")),
                    ui.text("Ожидаю подтверждение…", "Waiting for confirmation…"),
                )
                pollPairing(current, pollSecret)
            }
        }
    }

    private fun pollPairing(current: Int, pollSecret: String) {
        main.postDelayed({
            if (current != generation) return@postDelayed
            api.pollPairing(credentials.installationId, pollSecret) { result ->
                main.post {
                    if (current != generation) return@post
                    val response = result.getOrNull()
                    when {
                        response?.successful == true && response.payload.optString("status") == "connected" -> {
                            val token = response.payload.optString("access_token")
                            if (token.isBlank()) show(
                                ui.text("Ошибка привязки", "Pairing failed"),
                                listOf(ui.text("RokidHub не вернул токен.", "RokidHub did not return a token.")),
                                null,
                            )
                            else {
                                credentials.saveAccessToken(token)
                                checkDesktopAndListen(current)
                            }
                        }
                        response?.statusCode == 410 -> show(
                            ui.text("Код истёк", "Code expired"),
                            listOf(ui.text("Нажми, чтобы создать новый код.", "Press to create a new code.")),
                            null,
                        )
                        else -> pollPairing(current, pollSecret)
                    }
                }
            }
        }, POLL_INTERVAL_MS)
    }

    private fun checkDesktopAndListen(current: Int) {
        val token = credentials.readAccessToken() ?: return beginPairing(current)
        show(
            ui.text("Подключаю ПК", "Connecting to PC"),
            listOf(ui.text("Проверяю Desktop Connector…", "Checking Desktop Connector…")),
            null,
        )
        api.status(credentials.installationId, token) { result ->
            main.post {
                if (current != generation) return@post
                val response = result.getOrNull()
                if (response?.statusCode == 401) {
                    credentials.clearAccessToken()
                    beginPairing(current)
                    return@post
                }
                val connectors = response?.payload?.optJSONArray("desktop_connectors")
                if (response?.successful != true || connectors == null || connectors.length() == 0) {
                    show(
                        ui.text("Подключаю ПК", "Connecting to PC"),
                        listOf(ui.text("Привяжи и запусти Desktop Connector.", "Pair and start Desktop Connector.")),
                        ui.text("Затем нажми, чтобы проверить снова", "Then press to check again"),
                    )
                } else {
                    for (index in 0 until connectors.length()) {
                        val connector = connectors.optJSONObject(index) ?: continue
                        updateProjectName(connector.optString("default_project_name"))
                        if (credentials.projectName != null) break
                    }
                    beginListening(current)
                }
            }
        }
    }

    private fun beginListening(current: Int) {
        if (current != generation || speech != null) return
        submittedFinal = false
        showWork(
            "RokidHub · Codex",
            listOf(ui.text("Слушаю…", "Listening…")),
            ui.text("Скажи задачу или «выбери проект Рокид»", "Say a task or “select project Rokid”"),
        )
        val session = nexusSpeechSession(object : NexusSpeechCallbacks {
            override fun onSpeechStarted(realtime: Boolean) = Unit
            override fun onSpeechState(state: NexusSpeechState) {
                if (state == NexusSpeechState.PROCESSING && !submittedFinal) showWork(
                    "RokidHub · Codex",
                    listOf(ui.text("Распознаю…", "Recognizing…")),
                    null,
                )
            }
            override fun onSpeechPartial(text: String) {
                if (text.isNotBlank()) showWork("RokidHub · Codex", listOf(text.take(240)), ui.text("Слушаю…", "Listening…"))
            }
            override fun onSpeechFinal(text: String) {
                if (submittedFinal || text.isBlank()) return
                submittedFinal = true
                speech = null
                submit(current, text.trim())
            }
            override fun onSpeechStopped(reason: NexusSpeechStopReason, error: NexusSpeechError?) {
                speech = null
                if (current != generation || submittedFinal) return
                val message = when (reason) {
                    NexusSpeechStopReason.NO_SPEECH -> ui.text("Не расслышал запрос.", "I didn't hear a request.")
                    NexusSpeechStopReason.REVOKED -> ui.text("Разрешение STT отозвано в Nexus.", "STT permission was revoked in Nexus.")
                    NexusSpeechStopReason.LINK_LOST -> ui.text("Потеряна связь с очками.", "Connection to the glasses was lost.")
                    else -> error?.detail ?: ui.text("Распознавание остановлено.", "Speech recognition stopped.")
                }
                showWork("RokidHub · Codex", listOf(message.take(240)), ui.text("Нажми, чтобы повторить", "Press to try again"))
            }
        })
        speech = session
        if (session?.start(ui.speechLocale) != NexusSdkResult.SENT) {
            speech = null
            show(
                ui.text("Нет доступа к речи", "Speech unavailable"),
                listOf(ui.text("Разреши Speech to text для плагина в Nexus.", "Allow Speech to text for this plugin in Nexus.")),
                null,
            )
        }
    }

    private fun submit(current: Int, text: String) {
        val token = credentials.readAccessToken() ?: return beginPairing(current)
        val planned = CodexCommandPlanner.plan(text, credentials.conversationId != null, jobRunning)
        if (planned.action == "select_project") updateProjectName(planned.prompt)
        showWork(ui.text("Подключаю ПК", "Connecting to PC"), listOf(text.take(240)), null)
        api.createJob(credentials.installationId, token, planned, credentials.conversationId) { result ->
            main.post {
                if (current != generation) return@post
                val response = result.getOrNull()
                if (response?.statusCode == 401) {
                    credentials.clearAccessToken()
                    beginPairing(current)
                    return@post
                }
                if (response?.successful != true) {
                    show(
                        ui.text("Подключаю ПК", "Connecting to PC"),
                        listOf(response?.message() ?: ui.text("Нет связи с RokidHub.", "RokidHub is unavailable.")),
                        ui.text("Проверь Desktop Connector", "Check Desktop Connector"),
                    )
                    return@post
                }
                currentJobId = response.payload.optString("job_id")
                credentials.conversationId = response.payload.optString("conversation_id")
                updateProjectName(response.payload.optString("project_name"))
                jobRunning = true
                pollJob(current)
            }
        }
    }

    private fun pollJob(current: Int) {
        val token = credentials.readAccessToken() ?: return
        val jobId = currentJobId ?: return
        main.postDelayed({
            if (current != generation) return@postDelayed
            api.job(credentials.installationId, token, jobId) { result ->
                main.post {
                    if (current != generation) return@post
                    val response = result.getOrNull()
                    if (response?.successful != true) {
                        show(
                            ui.text("Нет связи с RokidHub", "RokidHub is unavailable"),
                            listOf(response?.message() ?: ui.text("Повтори позже.", "Try again later.")),
                            null,
                        )
                        jobRunning = false
                        return@post
                    }
                    val status = response.payload.optString("status")
                    val hud = ui.hudStatus(status, response.payload.optString("hud_status"))
                    updateProjectName(response.payload.optString("project_name"))
                    when (status) {
                        "queued", "dispatched", "running" -> {
                            showWork(
                                hud,
                                listOf(if (status == "running") ui.text("Анализ выполняется локально", "Analysis is running locally") else ui.text("Жду Connector", "Waiting for Connector")),
                                ui.text("Исходники остаются на ПК", "Source code stays on the PC"),
                            )
                            pollJob(current)
                        }
                        "needs_input" -> {
                            jobRunning = false
                            showWork(
                                ui.text("Нужен ответ", "Answer needed"),
                                listOf(ui.text("Codex ждёт уточнение.", "Codex needs clarification.")),
                                ui.text("Нажми и ответь", "Press and answer"),
                            )
                        }
                        "completed" -> finish(response.payload.optString("result").ifBlank { ui.text("Готово.", "Done.") })
                        "interrupted" -> finish(ui.text("Codex остановлен.", "Codex was stopped."))
                        else -> finish(response.payload.optString("result").ifBlank { ui.text("Codex не завершил задачу.", "Codex did not complete the task.") })
                    }
                }
            }
        }, JOB_POLL_INTERVAL_MS)
    }

    private fun finish(summary: String) {
        jobRunning = false
        currentJobId = null
        val short = summary.take(1024)
        showWork(
            ui.text("Готово", "Done"),
            listOf(short.take(240)),
            ui.text("Нажми, чтобы продолжить тот же диалог", "Press to continue the same conversation"),
        )
        speak(short)
    }

    private fun speak(text: String) {
        val session = tts ?: nexusTtsSession(object : NexusTtsCallbacks {
            override fun onTtsStarted(utteranceId: String) = Unit
            override fun onTtsDone(utteranceId: String, reason: NexusTtsDoneReason) = Unit
        })?.also { tts = it }
        session?.speak(text.take(1024))
    }

    private fun show(title: String, lines: List<String>, footer: String?) {
        val card = NexusCard(
            title = title,
            lines = lines,
            footer = footer,
            contentKey = "rokidhub-codex-${title.hashCode()}-${lines.hashCode()}",
            handlesBack = true,
        )
        val result = if (surfaceShown) surface?.updateCard(card) else surface?.showCard(card)
        if (result == NexusSdkResult.SENT) surfaceShown = true
    }

    private fun showWork(title: String, lines: List<String>, hint: String?) {
        show(title, lines, HudProjectLabel.footer(credentials.projectName, hint))
    }

    private fun updateProjectName(value: String?) {
        HudProjectLabel.normalize(value)?.let { credentials.projectName = it }
    }

    private companion object {
        const val SURFACE_ID = "main"
        const val POLL_INTERVAL_MS = 3_000L
        const val JOB_POLL_INTERVAL_MS = 2_000L
    }
}
