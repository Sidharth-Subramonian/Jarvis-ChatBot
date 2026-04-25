package com.piconsole.network

import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

object RetrofitClient {
    private var baseUrl: String? = null
    private var _apiService: ApiService? = null
    private var _webSocketManager: WebSocketManager? = null

    val isInitialized: Boolean get() = baseUrl != null

    val apiService: ApiService
        get() = _apiService ?: throw IllegalStateException("RetrofitClient not initialized")
        
    val webSocketManager: WebSocketManager
        get() = _webSocketManager ?: throw IllegalStateException("RetrofitClient not initialized")

    fun initialize(ip: String) {
        baseUrl = "http://$ip:8000/"
        _apiService = Retrofit.Builder()
            .baseUrl(baseUrl!!)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ApiService::class.java)
            
        _webSocketManager?.disconnect()
        _webSocketManager = WebSocketManager(baseUrl!!)
    }
}
