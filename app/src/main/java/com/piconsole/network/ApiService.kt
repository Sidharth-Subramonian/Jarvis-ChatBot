package com.piconsole.network

import com.piconsole.network.models.*
import retrofit2.http.*

data class DeviceRegistrationRequest(
    val token: String,
    val deviceName: String
)

interface ApiService {
    @GET("status")
    suspend fun getStatus(): StatusResponse

    @POST("timer")
    suspend fun createTimer(@Body request: TimerRequest): TimerResponse

    @DELETE("timer/{id}")
    suspend fun deleteTimer(@Path("id") id: String)

    @POST("alarm")
    suspend fun createAlarm(@Body request: AlarmRequest): AlarmResponse

    @DELETE("alarm/{id}")
    suspend fun deleteAlarm(@Path("id") id: String)

    @GET("stopwatch")
    suspend fun getStopwatchState(): StopwatchState

    @POST("stopwatch")
    suspend fun controlStopwatch(@Body request: StopwatchAction): StopwatchState

    @POST("media")
    suspend fun controlMedia(@Body request: MediaRequest): MediaResponse

    @POST("find-phone")
    suspend fun findPhone(): FindPhoneResponse

    @POST("reboot")
    suspend fun reboot(): StatusResponse

    @POST("shutdown")
    suspend fun shutdown(): StatusResponse

    @POST("mute")
    suspend fun mute(): StatusResponse

    @GET("jarvis/status")
    suspend fun getJarvisStatus(): JarvisStatusResponse

    @POST("jarvis/toggle")
    suspend fun toggleJarvis(): JarvisToggleResponse

    @POST("jarvis/command")
    suspend fun sendJarvisCommand(@Body request: JarvisCommandRequest): JarvisCommandResponse

    @POST("register-device")
    suspend fun registerDevice(@Body request: DeviceRegistrationRequest): StatusResponse
}
