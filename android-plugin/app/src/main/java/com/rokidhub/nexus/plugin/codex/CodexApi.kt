package com.rokidhub.nexus.plugin.codex

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

data class ApiResult(val statusCode: Int, val payload: JSONObject) {
    val successful: Boolean get() = statusCode in 200..299
    fun message(): String = payload.optString("result")
        .ifBlank { payload.optString("error") }
        .ifBlank { "RokidHub вернул ошибку $statusCode." }
}
class CodexApi(private val executor: ExecutorService = Executors.newSingleThreadExecutor()) {
    fun startPairing(installationId: String, callback: (Result<ApiResult>) -> Unit) = request(
        "POST",
        "/pairing/start",
        JSONObject().put("installation_id", installationId).put("plugin_id", PLUGIN_ID),
        callback = callback,
    )

    fun pollPairing(installationId: String, pollSecret: String, callback: (Result<ApiResult>) -> Unit) = request(
        "POST",
        "/pairing/poll",
        JSONObject()
            .put("installation_id", installationId)
            .put("plugin_id", PLUGIN_ID)
            .put("poll_secret", pollSecret),
        callback = callback,
    )

    fun status(installationId: String, token: String, callback: (Result<ApiResult>) -> Unit) = request(
        "POST", "/status", JSONObject(), installationId, token, callback,
    )

    fun createJob(
        installationId: String,
        token: String,
        planned: PlannedJob,
        conversationId: String?,
        callback: (Result<ApiResult>) -> Unit,
    ) {
        val payload = JSONObject()
            .put("action", planned.action)
            .put("prompt", planned.prompt)
            .put("client_request_id", UUID.randomUUID().toString())
        if (conversationId != null) payload.put("conversation_id", conversationId)
        request("POST", "/jobs", payload, installationId, token, callback)
    }

    fun job(installationId: String, token: String, jobId: String, callback: (Result<ApiResult>) -> Unit) = request(
        "GET", "/jobs/$jobId", null, installationId, token, callback,
    )

    fun close() = executor.shutdownNow()

    private fun request(
        method: String,
        path: String,
        payload: JSONObject?,
        installationId: String? = null,
        token: String? = null,
        callback: (Result<ApiResult>) -> Unit,
    ) {
        executor.execute {
            callback(runCatching {
                val connection = (URL(BuildConfig.ROKIDHUB_BASE_URL + path).openConnection() as HttpURLConnection).apply {
                    requestMethod = method
                    connectTimeout = 15_000
                    readTimeout = 25_000
                    setRequestProperty("Accept", "application/json")
                    if (payload != null) {
                        doOutput = true
                        setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    }
                    if (installationId != null && token != null) {
                        setRequestProperty("Authorization", "Bearer $token")
                        setRequestProperty("X-RokidHub-Installation-ID", installationId)
                    }
                }
                try {
                    if (payload != null) connection.outputStream.use {
                        it.write(payload.toString().toByteArray(Charsets.UTF_8))
                    }
                    val status = connection.responseCode
                    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                    val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                    ApiResult(status, if (body.isBlank()) JSONObject() else JSONObject(body))
                } finally {
                    connection.disconnect()
                }
            })
        }
    }

    companion object { const val PLUGIN_ID = "rokidhub.codex" }
}
