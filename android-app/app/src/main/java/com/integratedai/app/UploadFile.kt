package com.integratedai.app

/** A file picked in the app, held as base64 for the backend upload call.
 *  Contains file bytes only, never API keys. */
data class UploadFile(val name: String, val dataBase64: String)
