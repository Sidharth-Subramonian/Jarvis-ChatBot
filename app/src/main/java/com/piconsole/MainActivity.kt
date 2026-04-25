package com.piconsole

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import com.piconsole.ui.theme.PiConsoleTheme
import com.piconsole.navigation.PiConsoleNavHost
import com.google.firebase.messaging.FirebaseMessaging
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import com.piconsole.network.RetrofitClient
import com.piconsole.network.DeviceRegistrationRequest

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        val prefs = getSharedPreferences("crash_logs", android.content.Context.MODE_PRIVATE)
        val crashLog = prefs.getString("last_crash", null)
        
        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, exception ->
            prefs.edit().putString("last_crash", android.util.Log.getStackTraceString(exception)).commit()
            defaultHandler?.uncaughtException(thread, exception)
        }

        installSplashScreen()

        setContent {
            PiConsoleTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    if (crashLog != null) {
                        androidx.compose.foundation.lazy.LazyColumn(modifier = Modifier.fillMaxSize().padding(16.dp)) {
                            item {
                                androidx.compose.material3.Text(
                                    text = "APP CRASHED:\n\n$crashLog",
                                    color = androidx.compose.ui.graphics.Color.Red,
                                    style = androidx.compose.ui.text.TextStyle(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace)
                                )
                                androidx.compose.material3.Button(
                                    onClick = {
                                        prefs.edit().remove("last_crash").commit()
                                        finish()
                                    },
                                    modifier = Modifier.padding(top = 16.dp)
                                ) {
                                    androidx.compose.material3.Text("Clear Crash Log & Exit")
                                }
                            }
                        }
                    } else {
                        PiConsoleNavHost()
                    }
                }
            }
        }
    }
}
