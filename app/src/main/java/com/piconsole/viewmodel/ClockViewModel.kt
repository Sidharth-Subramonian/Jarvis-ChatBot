package com.piconsole.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.piconsole.network.RetrofitClient
import com.piconsole.network.models.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import okhttp3.MediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody
import java.io.File

class ClockViewModel : ViewModel() {
    private val _timers = MutableStateFlow<List<TimerResponse>>(emptyList())
    val timers: StateFlow<List<TimerResponse>> = _timers.asStateFlow()

    private val _alarms = MutableStateFlow<List<AlarmResponse>>(emptyList())
    val alarms: StateFlow<List<AlarmResponse>> = _alarms.asStateFlow()

    private val _ringtones = MutableStateFlow<List<RingtoneInfo>>(emptyList())
    val ringtones: StateFlow<List<RingtoneInfo>> = _ringtones.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    fun clearError() {
        _error.value = null
    }

    init {
        fetchRingtones()
        listenForClockEvents()
    }

    private fun listenForClockEvents() {
        viewModelScope.launch {
            try {
                RetrofitClient.webSocketManager.clockEvents.collect { event ->
                    when (event.type) {
                        "timer_created" -> {
                            val id = event.data["id"] as? String ?: return@collect
                            val label = event.data["label"] as? String ?: "Timer"
                            val remaining = (event.data["remainingSeconds"] as? Double)?.toInt() ?: 0
                            val ringtone = event.data["ringtone"] as? String ?: "default"
                            val newTimer = TimerResponse(id, label, remaining, ringtone)
                            if (!_timers.value.any { it.id == id }) {
                                _timers.value = _timers.value + newTimer
                            }
                        }
                        "timer_fired" -> {
                            val id = event.data["id"] as? String ?: return@collect
                            _timers.value = _timers.value.filter { it.id != id }
                        }
                        "timer_deleted" -> {
                            val id = event.data["id"] as? String ?: return@collect
                            _timers.value = _timers.value.filter { it.id != id }
                        }
                        "alarm_created" -> {
                            val id = event.data["id"] as? String ?: return@collect
                            val label = event.data["label"] as? String ?: "Alarm"
                            val time = event.data["timeFormatted"] as? String ?: ""
                            val ringtone = event.data["ringtone"] as? String ?: "default"
                            @Suppress("UNCHECKED_CAST")
                            val repeatDays = event.data["repeatDays"] as? List<String>
                            val newAlarm = AlarmResponse(id, label, time, true, ringtone, repeatDays)
                            if (!_alarms.value.any { it.id == id }) {
                                _alarms.value = _alarms.value + newAlarm
                            }
                        }
                        "alarm_deleted" -> {
                            val id = event.data["id"] as? String ?: return@collect
                            _alarms.value = _alarms.value.filter { it.id != id }
                        }
                    }
                }
            } catch (_: Exception) {
                // WebSocket not yet connected, will pick up events when it does
            }
        }
    }

    // --- Timers ---
    fun createTimer(label: String, durationSeconds: Int, ringtone: String = "default") {
        viewModelScope.launch {
            try {
                val newTimer = RetrofitClient.apiService.createTimer(TimerRequest(label, durationSeconds, ringtone))
                _timers.value = _timers.value + newTimer
            } catch (e: Exception) {
                _error.value = "Failed to create timer: ${e.localizedMessage}"
            }
        }
    }

    fun deleteTimer(id: String) {
        viewModelScope.launch {
            try {
                RetrofitClient.apiService.deleteTimer(id)
                _timers.value = _timers.value.filter { it.id != id }
            } catch (e: Exception) {
                _error.value = "Failed to delete timer: ${e.localizedMessage}"
            }
        }
    }

    // --- Alarms ---
    fun createAlarm(label: String, hours: Int, minutes: Int, amPm: String, ringtone: String = "default", repeatDays: List<String>? = null) {
        val formattedTime = String.format("%02d:%02d %s", hours, minutes, amPm)
        viewModelScope.launch {
            try {
                val newAlarm = RetrofitClient.apiService.createAlarm(AlarmRequest(label, formattedTime, ringtone, repeatDays))
                _alarms.value = _alarms.value + newAlarm
            } catch (e: Exception) {
                _error.value = "Failed to create alarm: ${e.localizedMessage}"
            }
        }
    }

    fun deleteAlarm(id: String) {
        viewModelScope.launch {
            try {
                RetrofitClient.apiService.deleteAlarm(id)
                _alarms.value = _alarms.value.filter { it.id != id }
            } catch (e: Exception) {
                _error.value = "Failed to delete alarm: ${e.localizedMessage}"
            }
        }
    }

    // --- Ringtones ---
    fun fetchRingtones() {
        viewModelScope.launch {
            try {
                val response = RetrofitClient.apiService.getRingtones()
                _ringtones.value = response.ringtones
            } catch (e: Exception) {
                // Ringtones will just show default if fetch fails
            }
        }
    }

    fun uploadRingtone(file: File) {
        viewModelScope.launch {
            try {
                val mediaType = MediaType.parse("audio/*")
                val requestBody = RequestBody.create(mediaType, file)
                val part = MultipartBody.Part.createFormData("file", file.name, requestBody)
                RetrofitClient.apiService.uploadRingtone(part)
                fetchRingtones() // Refresh list
            } catch (e: Exception) {
                _error.value = "Failed to upload ringtone: ${e.localizedMessage}"
            }
        }
    }
}
