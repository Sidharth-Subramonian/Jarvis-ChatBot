package com.piconsole.network.models

data class StatusResponse(
    val deviceName: String,
    val ipAddress: String,
    val uptime: String,
    val cpuUsage: Float,
    val ramUsage: Float,
    val temperature: Float,
    val isOnline: Boolean
)

data class TimerRequest(
    val label: String,
    val durationSeconds: Int
)

data class TimerResponse(
    val id: String,
    val label: String,
    val remainingSeconds: Int
)

data class AlarmRequest(
    val label: String,
    val timeFormatted: String
)

data class AlarmResponse(
    val id: String,
    val label: String,
    val timeFormatted: String,
    val isActive: Boolean
)

data class StopwatchAction(
    val action: String
)

data class StopwatchState(
    val isRunning: Boolean,
    val elapsedMilliseconds: Long
)

data class MediaRequest(
    val action: String, // "play", "pause", "next", "prev", "volume"
    val volume: Float? = null
)

data class MediaResponse(
    val status: String,
    val currentTrack: String? = null,
    val volume: Float? = null
)

data class FindPhoneResponse(
    val success: Boolean,
    val message: String
)

data class JarvisStatusResponse(
    val isRunning: Boolean,
    val enabled: Boolean
)

data class JarvisToggleResponse(
    val message: String
)

data class JarvisCommandRequest(
    val command: String
)

data class JarvisCommandResponse(
    val message: String,
    val command: String
)
