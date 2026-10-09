package com.davidfwatson.partymail

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.ViewModelProvider

class MainActivity : ComponentActivity() {
    private lateinit var model: PartyModel
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        model = ViewModelProvider(this)[PartyModel::class.java]
        val incoming = intent?.dataString
        val forwarded = savedInstanceState == null && forwardWebsiteLink(incoming)
        if (!model.bootstrapped && !model.busy) model.start(if (forwarded) null else incoming)
        setContent { PartyApp(model, this) }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.dataString?.let { raw ->
            if (!forwardWebsiteLink(raw)) model.openRaw(raw)
        }
    }
    private fun forwardWebsiteLink(raw: String?): Boolean {
        if (raw == null || !BrowserRoutes.shouldOpen(raw, model.api.origin)) return false
        openWeb(this, raw)
        return true
    }
}
