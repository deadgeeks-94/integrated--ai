package com.integratedai.app

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Talks only to the Python backend. No AI provider keys live here.
 * Keys stay in server-side env vars (OPENAI_API_KEY etc).
 */
class ApiClient(private val baseUrl: String) {

    private fun normalized(): String = baseUrl.trimEnd('/')

    private fun get(path: String): String {
        val conn = (URL(normalized() + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 8000
            readTimeout = 15000
        }
        try {
            val stream = if (conn.responseCode in 200..299) conn.inputStream else conn.errorStream
            return stream.bufferedReader().use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }

    private fun postJson(path: String, body: JSONObject, readTimeoutMs: Int = 90000): JSONObject {
        val conn = (URL(normalized() + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 10000
            readTimeout = readTimeoutMs
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
        }
        try {
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val stream = if (conn.responseCode in 200..299) conn.inputStream else conn.errorStream
            val text = stream.bufferedReader().use { it.readText() }
            return JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }

    suspend fun health(): String = withContext(Dispatchers.IO) { get("/health") }

    suspend fun providers(): String = withContext(Dispatchers.IO) { get("/providers") }

    suspend fun chat(message: String, agent: String, provider: String, sessionId: String): String =
        withContext(Dispatchers.IO) {
            val body = JSONObject().apply {
                put("message", message)
                put("agent", agent)
                put("provider", provider)
                put("session_id", sessionId)
            }
            postJson("/chat", body).optString("reply", "(no reply field)")
        }

    /** One-shot file analysis against POST /upload/analyze. Images go to the backend's
     *  vision-capable provider (OpenAI/Gemini/Claude); documents/text are extracted server-side. */
    suspend fun analyzeFiles(
        question: String,
        agent: String,
        provider: String,
        sessionId: String,
        files: List<UploadFile>
    ): String = withContext(Dispatchers.IO) {
        val arr = JSONArray()
        for (f in files) {
            arr.put(JSONObject().apply {
                put("filename", f.name)
                put("data_b64", f.dataBase64)
            })
        }
        val body = JSONObject().apply {
            put("question", question.ifBlank { "Analyze these files." })
            put("agent", agent)
            put("provider", provider)
            put("session_id", sessionId)
            put("files", arr)
        }
        // File uploads can take a while: analysis + provider round trip.
        postJson("/upload/analyze", body, readTimeoutMs = 180000).optString("reply", "(no reply field)")
    }

    /** Lists files in the session workspace (generated/downloadable files). */
    suspend fun workspaceList(sessionId: String): String =
        withContext(Dispatchers.IO) { get("/workspace/list?session_id=" + sessionId) }

    /** Returns the download URL for a workspace file (open in browser to save). */
    fun workspaceDownloadUrl(sessionId: String, filename: String): String =
        normalized() + "/workspace/download?session_id=" + sessionId + "&file=" + filename

    suspend fun memorySessions(): String = withContext(Dispatchers.IO) { get("/memory/sessions") }

    suspend fun clear(sessionId: String): String = withContext(Dispatchers.IO) {
        postJson("/clear", JSONObject().put("session_id", sessionId), readTimeoutMs = 8000).toString()
    }
}
