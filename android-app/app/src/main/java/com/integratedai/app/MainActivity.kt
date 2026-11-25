package com.integratedai.app

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
import androidx.appcompat.app.AlertDialog
import androidx.drawerlayout.widget.DrawerLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.launch
import org.json.JSONObject

class MainActivity : AppCompatActivity() {

    private lateinit var store: SettingsStore
    private lateinit var adapter: ChatAdapter
    private lateinit var statusText: TextView
    private lateinit var urlInput: EditText
    private lateinit var accessTokenInput: EditText
    private lateinit var messageInput: EditText
    private lateinit var providerSpinner: Spinner
    private lateinit var agentSpinner: Spinner
    private lateinit var attachButton: Button
    private lateinit var analyzeButton: Button
    private lateinit var attachedText: TextView
    private lateinit var drawerLayout: DrawerLayout

    private val providerValues = mutableListOf<String>()
    private val pending = mutableListOf<UploadFile>()
    private var sessionId = "android-1"
    private var latestAssistantReply = ""
    private var pendingDownloadBytes: ByteArray? = null

    private val pickFiles = registerForActivityResult(
        ActivityResultContracts.OpenMultipleDocuments()
    ) { uris: List<Uri> ->
        if (uris.isEmpty()) return@registerForActivityResult
        lifecycleScope.launch {
            for (uri in uris) {
                try {
                    pending.add(readUri(uri))
                } catch (e: Exception) {
                    Toast.makeText(this@MainActivity, "Could not read file: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
            refreshAttachedLabel()
            Toast.makeText(this@MainActivity, "${pending.size} file(s) attached", Toast.LENGTH_SHORT).show()
        }
    }

    private val createWorkspaceDocument = registerForActivityResult(
        ActivityResultContracts.CreateDocument("application/octet-stream")
    ) { uri: Uri? ->
        if (uri == null) {
            pendingDownloadBytes = null
            return@registerForActivityResult
        }
        lifecycleScope.launch {
            try {
                val bytes = pendingDownloadBytes ?: throw IllegalStateException("No file data to save.")
                contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                    ?: throw IllegalStateException("Could not open the selected destination.")
                statusText.text = "Workspace file downloaded."
                Toast.makeText(this@MainActivity, "File saved.", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                statusText.text = "Save download failed: ${e.message}"
            } finally {
                pendingDownloadBytes = null
            }
        }
    }

    private fun client() = ApiClient(store.backendUrl, accessTokenInput.text.toString())

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
        if (ext !in allowed) throw IllegalArgumentException("Unsupported file type: .$ext")
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
        attachedText.text = if (pending.isEmpty()) getString(R.string.no_attachments)
        else "Attached: " + pending.joinToString(", ") { it.name }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        store = SettingsStore(this)
        drawerLayout = findViewById(R.id.drawerLayout)
        statusText = findViewById(R.id.statusText)
        urlInput = findViewById(R.id.backendUrlInput)
        accessTokenInput = findViewById(R.id.accessTokenInput)
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

        loadProviderOptions()
        agentSpinner.adapter = ArrayAdapter.createFromResource(
            this, R.array.agents, android.R.layout.simple_spinner_item
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
        findViewById<Button>(R.id.menuButton).setOnClickListener { drawerLayout.openDrawer(android.view.Gravity.START) }
        findViewById<Button>(R.id.clearButton).setOnClickListener {
            drawerLayout.closeDrawers()
            lifecycleScope.launch {
                try {
                    client().clear(sessionId)
                    adapter.clear()
                    latestAssistantReply = ""
                    statusText.text = "Chat cleared on server."
                } catch (e: Exception) {
                    statusText.text = "Clear failed: ${e.message}"
                }
            }
        }
        findViewById<Button>(R.id.newChatMenuButton).setOnClickListener {
            drawerLayout.closeDrawers()
            findViewById<Button>(R.id.clearButton).performClick()
        }
        findViewById<Button>(R.id.searchChatsButton).setOnClickListener {
            drawerLayout.closeDrawers()
            showMemorySessions()
        }
        findViewById<Button>(R.id.imagesButton).setOnClickListener {
            drawerLayout.closeDrawers()
            pickFiles.launch(arrayOf("image/*"))
        }
        findViewById<Button>(R.id.libraryButton).setOnClickListener {
            drawerLayout.closeDrawers()
            showWorkspaceFiles()
        }
        findViewById<Button>(R.id.customizeButton).setOnClickListener {
            drawerLayout.closeDrawers()
            AlertDialog.Builder(this)
                .setTitle("Customize Integrated AI")
                .setMessage("Choose your AI provider and assistant style from the selectors above the conversation. More appearance and behavior options can be added here.")
                .setPositiveButton("Got it", null)
                .show()
        }
        findViewById<Button>(R.id.remoteButton).setOnClickListener {
            drawerLayout.closeDrawers()
            Toast.makeText(this, "Remote tools are not configured yet.", Toast.LENGTH_SHORT).show()
        }
        findViewById<Button>(R.id.exploreButton).setOnClickListener {
            drawerLayout.closeDrawers()
            Toast.makeText(this, "Explore will be added in a later update.", Toast.LENGTH_SHORT).show()
        }
        findViewById<Button>(R.id.projectButton).setOnClickListener {
            drawerLayout.closeDrawers()
            chooseProject()
        }
        findViewById<Button>(R.id.memoryButton).setOnClickListener {
            drawerLayout.closeDrawers()
            showMemorySessions()
        }
        findViewById<Button>(R.id.workspaceButton).setOnClickListener {
            drawerLayout.closeDrawers()
            showWorkspaceFiles()
        }
        findViewById<Button>(R.id.saveReplyButton).setOnClickListener {
            drawerLayout.closeDrawers()
            saveLatestReply()
        }
        findViewById<Button>(R.id.sendButton).setOnClickListener { sendMessage() }
        attachButton.setOnClickListener { pickFiles.launch(arrayOf("*/*")) }
        analyzeButton.setOnClickListener { analyzeAttachments() }
        checkBackend()
    }

    private fun chooseProject() {
        val input = EditText(this).apply {
            hint = "Project name"
            setText(if (sessionId.startsWith("project/")) sessionId.removePrefix("project/") else "")
        }
        AlertDialog.Builder(this)
            .setTitle("Project workspace")
            .setMessage("Use a project name to keep its conversation memory and files separate.")
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Use project") { _, _ ->
                val name = input.text.toString().trim()
                    .replace(Regex("[^A-Za-z0-9._-]+"), "-")
                    .trim('-', '.', '_')
                if (name.isBlank()) {
                    Toast.makeText(this, "Enter a valid project name.", Toast.LENGTH_SHORT).show()
                } else {
                    sessionId = "project/" + name
                    adapter.clear()
                    latestAssistantReply = ""
                    statusText.text = "Active session: $sessionId"
                }
            }
            .show()
    }

    private fun saveLatestReply() {
        if (latestAssistantReply.isBlank()) {
            Toast.makeText(this, "There is no AI reply to save yet.", Toast.LENGTH_SHORT).show()
            return
        }
        val filename = EditText(this).apply {
            setText("assistant-response.txt")
            selectAll()
        }
        AlertDialog.Builder(this)
            .setTitle("Save AI reply")
            .setMessage("Save the latest AI response to this session's workspace.")
            .setView(filename)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Save") { _, _ ->
                val name = filename.text.toString().trim()
                lifecycleScope.launch {
                    try {
                        client().workspaceSave(sessionId, name, latestAssistantReply)
                        statusText.text = "Saved $name to workspace."
                    } catch (e: Exception) {
                        statusText.text = "Workspace save failed: ${e.message}"
                    }
                }
            }
            .show()
    }

    private fun showWorkspaceFiles() {
        lifecycleScope.launch {
            try {
                val data = JSONObject(client().workspaceList(sessionId))
                val files = data.optJSONArray("files")
                if (files == null || files.length() == 0) {
                    Toast.makeText(this@MainActivity, "This workspace is empty.", Toast.LENGTH_SHORT).show()
                    return@launch
                }
                val names = (0 until files.length()).map { files.getJSONObject(it).optString("file") }
                AlertDialog.Builder(this@MainActivity)
                    .setTitle("Workspace · $sessionId")
                    .setItems(names.toTypedArray()) { _, which ->
                        val selected = names[which]
                        lifecycleScope.launch {
                            try {
                                statusText.text = "Downloading $selected ..."
                                pendingDownloadBytes = client().workspaceDownload(sessionId, selected)
                                createWorkspaceDocument.launch(selected)
                            } catch (e: Exception) {
                                pendingDownloadBytes = null
                                statusText.text = "Download failed: ${e.message}"
                            }
                        }
                    }
                    .setNegativeButton("Close", null)
                    .show()
            } catch (e: Exception) {
                statusText.text = "Could not load workspace: ${e.message}"
            }
        }
    }

    private fun showMemorySessions() {
        lifecycleScope.launch {
            try {
                val data = JSONObject(client().memorySessions())
                val sessions = data.optJSONArray("sessions")
                if (sessions == null || sessions.length() == 0) {
                    Toast.makeText(this@MainActivity, "No saved conversation sessions yet.", Toast.LENGTH_SHORT).show()
                    return@launch
                }
                val labels = (0 until sessions.length()).map { i ->
                    val item = sessions.getJSONObject(i)
                    "${item.optString("session_id")} · ${item.optInt("turns")} turns"
                }
                AlertDialog.Builder(this@MainActivity)
                    .setTitle("Saved memory sessions")
                    .setItems(labels.toTypedArray()) { _, which ->
                        val selected = sessions.getJSONObject(which).optString("session_id")
                        sessionId = selected
                        adapter.clear()
                        latestAssistantReply = ""
                        statusText.text = "Active session: $sessionId"
                    }
                    .setNegativeButton("Close", null)
                    .show()
            } catch (e: Exception) {
                statusText.text = "Could not load memory sessions: ${e.message}"
            }
        }
    }

    private fun loadProviderOptions() {
        lifecycleScope.launch {
            val names = linkedMapOf(
                "openai" to "OpenAI",
                "gemini" to "Gemini",
                "claude" to "Claude",
                "deepseek" to "DeepSeek"
            )
            val configured = mutableSetOf<String>()
            try {
                val data = JSONObject(client().providers())
                val providers = data.optJSONObject("providers")
                names.keys.forEach { key ->
                    if (providers?.optJSONObject(key)?.optBoolean("configured", false) == true) configured.add(key)
                }
            } catch (_: Exception) {
                // Keep the selector usable if the capability endpoint is temporarily unavailable.
            }
            providerValues.clear()
            providerValues.add("combined")
            names.keys.forEach { providerValues.add(it) }
            val labels = mutableListOf("Combined AI Council · ${configured.size}/4 connected")
            names.forEach { (key, label) ->
                labels.add("$label · " + if (key in configured) "Configured" else "Not configured")
            }
            providerSpinner.adapter = ArrayAdapter(
                this@MainActivity, android.R.layout.simple_spinner_item, labels
            ).also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
            statusText.text = "AI providers: ${configured.size} of 4 configured. Combined AI Council uses connected providers only."
        }
    }

    private fun selectedProvider(): String =
        providerValues.getOrNull(providerSpinner.selectedItemPosition) ?: "auto"

    private fun checkBackend() {
        statusText.text = "Checking ${store.backendUrl} ..."
        loadProviderOptions()
        lifecycleScope.launch {
            try {
                val health = client().health()
                val providers = try { client().providers() } catch (e: Exception) { "(providers endpoint unavailable)" }
                statusText.text = "Health: $health\nProviders: $providers"
            } catch (e: Exception) {
                statusText.text = "Cannot reach backend at ${store.backendUrl}. Error: ${e.message}"
            }
        }
    }

    private fun sendMessage() {
        val text = messageInput.text.toString().trim()
        if (text.isEmpty()) return
        val provider = selectedProvider()
        val agent = agentSpinner.selectedItem.toString()
        adapter.add(ChatMessage("user", text))
        messageInput.text.clear()
        statusText.text = "Sending to $provider / $agent ..."
        lifecycleScope.launch {
            try {
                val reply = client().chat(text, agent, provider, sessionId)
                latestAssistantReply = reply
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
        val provider = selectedProvider()
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
                val reply = client().analyzeFiles(question, agent, provider, sessionId, files)
                latestAssistantReply = reply
                adapter.add(ChatMessage("assistant", reply))
                statusText.text = "Done."
            } catch (e: Exception) {
                statusText.text = "Analyze failed: ${e.message}"
                adapter.add(ChatMessage("assistant", "Error: ${e.message}"))
            }
        }
    }
}
