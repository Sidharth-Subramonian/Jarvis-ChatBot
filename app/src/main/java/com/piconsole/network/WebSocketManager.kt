package com.piconsole.network

import android.util.Log
import com.google.gson.Gson
import com.piconsole.network.models.StatusResponse
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.*
import java.util.concurrent.TimeUnit

data class ClockEvent(val type: String, val data: Map<String, Any>)

class WebSocketManager(private val baseUrl: String) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private val gson = Gson()

    private val _statusUpdate = MutableStateFlow<StatusResponse?>(null)
    val statusUpdate: StateFlow<StatusResponse?> = _statusUpdate.asStateFlow()

    private val _isConnected = MutableStateFlow(false)
    val isConnected: StateFlow<Boolean> = _isConnected.asStateFlow()

    // Clock events (timer/alarm created, fired, deleted)
    private val _clockEvents = MutableSharedFlow<ClockEvent>(extraBufferCapacity = 10)
    val clockEvents: SharedFlow<ClockEvent> = _clockEvents.asSharedFlow()

    fun connect() {
        val wsUrl = baseUrl.replace("http", "ws") + "ws"
        val request = Request.Builder().url(wsUrl).build()
        
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d("WebSocket", "Connected to $wsUrl")
                _isConnected.value = true
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val wrapper = gson.fromJson(text, Map::class.java)
                    val type = wrapper["type"] as? String ?: return
                    
                    when (type) {
                        "status" -> {
                            val dataJson = gson.toJson(wrapper["data"])
                            val status = gson.fromJson(dataJson, StatusResponse::class.java)
                            _statusUpdate.value = status
                        }
                        "timer_created", "timer_fired", "timer_deleted",
                        "alarm_created", "alarm_fired", "alarm_deleted",
                        "media_update" -> {
                            @Suppress("UNCHECKED_CAST")
                            val data = wrapper["data"] as? Map<String, Any> ?: emptyMap()
                            _clockEvents.tryEmit(ClockEvent(type, data))
                            Log.d("WebSocket", "Clock event: $type")
                        }
                    }
                } catch (e: Exception) {
                    Log.e("WebSocket", "Error parsing message", e)
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                _isConnected.value = false
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e("WebSocket", "Connection failed", t)
                _isConnected.value = false
            }
        })
    }

    fun disconnect() {
        webSocket?.close(1000, "App closed")
        webSocket = null
    }
}
