package com.integratedai.app

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Talks only to the Python backend. No AI provider keys live here.
 * Keys stay in server-side env vars (OPENAI_API_KEY etc).
 */
class ApiClient(private val baseUrl: String, private val accessToken: String = "") {

    private fun normalized(): String = baseUrl.trimEnd('/')
    private fun queryValue(value: String): String = URLEncoder.encode(value, "UTF-8")

    private fun get(path: String): String {
        val conn = (URL(normalized() + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            if (accessToken.isNotBlank()) setRequestProperty("Authorization", "Bearer $accessToken")
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

    private fun getBytes(path: String): ByteArray {
        val conn = (URL(normalized() + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            if (accessToken.isNotBlank()) setRequestProperty("Authorization", "Bearer $accessToken")
            connectTimeout = 10000
            readTimeout = 30000
        }
        try {
            val code = conn.responseCode
            if (code !in 200..299) {
                val detail = conn.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                throw IOException("Download failed (HTTP $code): $detail")
            }
            return conn.inputStream.use { it.readBytes() }
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
            if (accessToken.isNotBlank()) setRequestProperty("Authorization", "Bearer $accessToken")
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

    /** One-shot file analysis; file bytes go only to the backend. */
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
        postJson("/upload/analyze", body, readTimeoutMs = 180000)
            .optString("reply", "(no reply field)")
    }

    /** Lists files in this session's workspace. */
    suspend fun workspaceList(sessionId: String): String =
        withContext(Dispatchers.IO) {
            get("/workspace/list?session_id=" + queryValue(sessionId))
        }

    /** Saves generated text/code in the session workspace. */
    suspend fun workspaceSave(sessionId: String, filename: String, content: String): String =
        withContext(Dispatchers.IO) {
            val body = JSONObject().apply {
                put("session_id", sessionId)
                put("filename", filename)
                put("content", content)
            }
            postJson("/workspace/save", body).toString()
        }

    /** Applies one exact text replacement to an existing workspace file. */
    suspend fun workspaceEdit(
        sessionId: String,
        filename: String,
        oldText: String,
        newText: String
    ): String = withContext(Dispatchers.IO) {
        val body = JSONObject().apply {
            put("session_id", sessionId)
            put("filename", filename)
            put("old_text", oldText)
            put("new_text", newText)
        }
        postJson("/workspace/edit", body).toString()
    }

    /** Downloads bytes directly with Authorization; do not open the protected URL in a browser. */
    suspend fun workspaceDownload(sessionId: String, filename: String): ByteArray =
        withContext(Dispatchers.IO) {
            val path = "/workspace/download?session_id=" + queryValue(sessionId) +
                "&file=" + queryValue(filename)
            getBytes(path)
        }

    suspend fun memorySessions(): String =
        withContext(Dispatchers.IO) { get("/memory/sessions") }

    suspend fun clear(sessionId: String): String = withContext(Dispatchers.IO) {
        postJson("/clear", JSONObject().put("session_id", sessionId), readTimeoutMs = 8000).toString()
    }
}
