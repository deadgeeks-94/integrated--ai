package com.integratedai.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Base64
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var store: SettingsStore
    private lateinit var adapter: ChatAdapter
    private lateinit var statusText: TextView
    private lateinit var urlInput: EditText
    private lateinit var messageInput: EditText
    private lateinit var providerSpinner: Spinner
    private lateinit var agentSpinner: Spinner
    private lateinit var attachButton: Button
    private lateinit var analyzeButton: Button
    private lateinit var attachedText: TextView

    // Pending attachments (images, pdf, docx, text) read into memory as base64.
    // Nothing is sent to any AI provider directly; files go only to the backend URL.
    private val pending = mutableListOf<UploadFile>()

    // Project-style session: switch to "project/<name>" for persistent project memory + workspace.
    private var sessionId = "android-1"

    // Lets the user pick images or documents. May return null entries in extras.
    private val pickFiles = registerForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments()
    ) { uris: List<Uri> ->
        if (uris.isEmpty()) return@registerForActivityResult
        lifecycleScope.launch {
            for (uri in uris) {
                try {
                    val f = readUri(uri)
                    pending.add(f)
                } catch (e: Exception) {
                    Toast.makeText(this@MainActivity, "Could not read file: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
            refreshAttachedLabel()
            Toast.makeText(this@MainActivity, "${pending.size} file(s) attached", Toast.LENGTH_SHORT).show()
        }
    }

    private fun readUri(uri: Uri): UploadFile {
        val name = queryDisplayName(uri) ?: "file"
        val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: throw IllegalArgumentException("empty or unreadable file")
        val ext = name.substringAfterLast('.', "").lowercase()
        val allowed = setOf(
            "jpg", "jpeg", "png", "gif", "webp", "pdf", "docx", "txt", "md", "py",
            "json", "csv", "html", "htm", "js", "ts", "sh", "yml", "yaml", "log",
            "xml", "css", "java", "c", "cpp", "go", "rs", "sql", "ini", "toml", "zip"
        )
        if (ext !in allowed) {
            throw IllegalArgumentException(
                "Unsupported type .$ext. Supported: images (jpg/png/gif/webp), pdf, docx, and text/code files."
            )
        }
        // No hard client cap: the backend enforces its configurable limits
        // (UPLOAD_MAX_BYTES etc) and reports oversize files clearly.
        return UploadFile(name, Base64.encodeToString(bytes, Base64.NO_WRAP))
    }

    private fun queryDisplayName(uri: Uri): String? {
        return try {
            contentResolver.query(uri, null, null, null, null)?.use { c ->
                val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0 && c.moveToFirst()) c.getString(idx) else null
            }
        } catch (e: Exception) {
            null
        }
    }

    private fun refreshAttachedLabel() {
        attachedText.text = if (pending.isEmpty()) {
            getString(R.string.no_attachments)
        } else {
            "Attached: " + pending.joinToString(", ") { it.name }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        store = SettingsStore(this)
        statusText = findViewById(R.id.statusText)
        urlInput = findViewById(R.id.backendUrlInput)
        messageInput = findViewById(R.id.messageInput)
        providerSpinner = findViewById(R.id.providerSpinner)
        agentSpinner = findViewById(R.id.agentSpinner)
        attachButton = findViewById(R.id.attachButton)
        analyzeButton = findViewById(R.id.analyzeButton)
        attachedText = findViewById(R.id.attachedText)

        urlInput.setText(store.backendUrl)

        adapter = ChatAdapter()
        val recycler: RecyclerView = findViewById(R.id.chatRecycler)
        recycler.layoutManager = LinearLayoutManager(this)
        recycler.adapter = adapter

        providerSpinner.adapter = ArrayAdapter.createFromResource(
            this,
            R.array.providers,
            android.R.layout.simple_spinner_item
        ).also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }

        agentSpinner.adapter = ArrayAdapter.createFromResource(
            this,
            R.array.agents,
            android.R.layout.simple_spinner_item
        ).also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }

        findViewById<Button>(R.id.saveUrlButton).setOnClickListener {
            val url = urlInput.text.toString().trim()
            if (url.startsWith("http://") || url.startsWith("https://")) {
                store.backendUrl = url
                Toast.makeText(this, "Saved backend URL", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "URL must start with http:// or https://", Toast.LENGTH_LONG).show()
            }
        }

        findViewById<Button>(R.id.checkButton).setOnClickListener { checkBackend() }

        findViewById<Button>(R.id.clearButton).setOnClickListener {
            lifecycleScope.launch {
                try {
                    ApiClient(store.backendUrl).clear(sessionId)
                    adapter.clear()
                    statusText.text = "Chat cleared on server."
                } catch (e: Exception) {
                    statusText.text = "Clear failed: ${e.message}"
                }
            }
        }

        findViewById<Button>(R.id.sendButton).setOnClickListener { sendMessage() }

        attachButton.setOnClickListener {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
                putExtra(Intent.EXTRA_MIME_TYPES, arrayOf(
                    "image/*", "application/pdf",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/zip", "text/*", "application/json", "application/csv"
                ))
                putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            }
            pickFiles.launch(arrayOf("*/*"))
        }

        analyzeButton.setOnClickListener { analyzeAttachments() }

        checkBackend()
    }

    private fun checkBackend() {
        statusText.text = "Checking ${store.backendUrl} ..."
        lifecycleScope.launch {
            try {
                val client = ApiClient(store.backendUrl)
                val health = client.health()
                val providers = try { client.providers() } catch (e: Exception) { "(providers endpoint unavailable)" }
                statusText.text = "Health: $health\nProviders: $providers"
            } catch (e: Exception) {
                statusText.text = "Cannot reach backend at ${store.backendUrl}. Is the Python server running? Emulator note: host localhost is 10.0.2.2, not 127.0.0.1. Error: ${e.message}"
            }
        }
    }

    private fun sendMessage() {
        val text = messageInput.text.toString().trim()
        if (text.isEmpty()) return
        val provider = providerSpinner.selectedItem.toString()
        val agent = agentSpinner.selectedItem.toString()

        adapter.add(ChatMessage("user", text))
        messageInput.text.clear()
        statusText.text = "Sending to $provider / $agent ..."

        lifecycleScope.launch {
            try {
                val reply = ApiClient(store.backendUrl).chat(text, agent, provider, sessionId)
                adapter.add(ChatMessage("assistant", reply))
                statusText.text = "Done."
            } catch (e: Exception) {
                statusText.text = "Send failed: ${e.message}"
                adapter.add(ChatMessage("assistant", "Error: ${e.message}"))
            }
        }
    }

    private fun analyzeAttachments() {
        if (pending.isEmpty()) {
            Toast.makeText(this, "Attach a file first (images, pdf, docx, or text)", Toast.LENGTH_LONG).show()
            return
        }
        val question = messageInput.text.toString().trim()
        val provider = providerSpinner.selectedItem.toString()
        val agent = agentSpinner.selectedItem.toString()
        val files = pending.toList()

        adapter.add(ChatMessage("user", "Analyze: " + files.joinToString(", ") { it.name } +
            if (question.isNotEmpty()) "\n$question" else ""))
        messageInput.text.clear()
        statusText.text = "Uploading ${files.size} file(s) for $provider / $agent analysis ..."
        pending.clear()
        refreshAttachedLabel()

        lifecycleScope.launch {
            try {
                val reply = ApiClient(store.backendUrl).analyzeFiles(question, agent, provider, sessionId, files)
                adapter.add(ChatMessage("assistant", reply))
                statusText.text = "Done."
            } catch (e: Exception) {
                statusText.text = "Analyze failed: ${e.message}"
                adapter.add(ChatMessage("assistant", "Error: ${e.message}"))
            }
        }
    }
}
