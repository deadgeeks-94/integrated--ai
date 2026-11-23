package com.integratedai.app

import android.content.Context
import android.content.SharedPreferences
import android.preference.PreferenceManager

class SettingsStore(context: Context) {
    private val prefs: SharedPreferences =
        PreferenceManager.getDefaultSharedPreferences(context)

    var backendUrl: String
        get() = prefs.getString(KEY_URL, DEFAULT_URL) ?: DEFAULT_URL
        set(value) = prefs.edit().putString(KEY_URL, value).apply()

    companion object {
        private const val KEY_URL = "backend_url"
        // Android emulator maps host localhost to 10.0.2.2
        const val DEFAULT_URL = "http://10.0.2.2:8000"
    }
}
