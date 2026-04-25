package com.piconsole.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.piconsole.network.RetrofitClient
import com.piconsole.network.models.MediaRequest
import com.piconsole.network.models.MediaResponse
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class MediaViewModel : ViewModel() {
    private val _mediaState = MutableStateFlow<MediaResponse?>(null)
    val mediaState: StateFlow<MediaResponse?> = _mediaState.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    init {
        listenForMediaEvents()
    }

    private fun listenForMediaEvents() {
        viewModelScope.launch {
            try {
                RetrofitClient.webSocketManager.clockEvents.collect { event ->
                    if (event.type == "media_update") {
                        val status = event.data["status"] as? String ?: ""
                        val track = event.data["currentTrack"] as? String
                        val volume = (event.data["volume"] as? Double)?.toFloat()
                        _mediaState.value = MediaResponse(status, track, volume)
                    }
                }
            } catch (_: Exception) {}
        }
    }

    fun sendMediaAction(action: String, volume: Float? = null, query: String? = null) {
        viewModelScope.launch {
            try {
                val response = RetrofitClient.apiService.controlMedia(MediaRequest(action, volume, query))
                _mediaState.value = response
            } catch (e: Exception) {
                _error.value = "Failed to send media action: ${e.message}"
            }
        }
    }

    fun clearError() {
        _error.value = null
    }
}
