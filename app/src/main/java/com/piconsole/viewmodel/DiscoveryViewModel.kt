package com.piconsole.viewmodel

import android.app.Application
import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.nio.charset.StandardCharsets

data class DiscoveredDevice(
    val name: String,
    val ip: String,
    val model: String
)

class DiscoveryViewModel(application: Application) : AndroidViewModel(application) {
    private val nsdManager = application.getSystemService(Context.NSD_SERVICE) as NsdManager
    
    private val _devices = MutableStateFlow<List<DiscoveredDevice>>(emptyList())
    val devices: StateFlow<List<DiscoveredDevice>> = _devices.asStateFlow()
    
    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning.asStateFlow()

    private val discoveryListener = object : NsdManager.DiscoveryListener {
        override fun onDiscoveryStarted(regType: String) {
            _isScanning.value = true
        }
        override fun onServiceFound(service: NsdServiceInfo) {
            if (service.serviceType == "_piconsole._tcp.local.") {
                nsdManager.resolveService(service, resolveListener)
            }
        }
        override fun onServiceLost(service: NsdServiceInfo) { }
        override fun onDiscoveryStopped(serviceType: String) {
            _isScanning.value = false
        }
        override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
            nsdManager.stopServiceDiscovery(this)
            _isScanning.value = false
        }
        override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
            nsdManager.stopServiceDiscovery(this)
        }
    }

    private val resolveListener = object : NsdManager.ResolveListener {
        override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) { }
        override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
            val name = serviceInfo.serviceName
            val ip = serviceInfo.host.hostAddress
            
            // In Android API levels below 21, attributes aren't easily parsed this way.
            // But targetSdk is 34 so we should be good.
            var model = "Raspberry Pi"
            try {
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.LOLLIPOP) {
                    serviceInfo.attributes["model"]?.let {
                        model = String(it, StandardCharsets.UTF_8)
                    }
                }
            } catch (e: Exception) {}
            
            if (ip != null) {
                val newDevice = DiscoveredDevice(name, ip, model)
                if (!_devices.value.any { it.ip == ip }) {
                    _devices.value = _devices.value + newDevice
                }
            }
        }
    }

    fun startDiscovery() {
        try {
            _devices.value = emptyList()
            nsdManager.discoverServices("_piconsole._tcp.local.", NsdManager.PROTOCOL_DNS_SD, discoveryListener)
        } catch (e: Exception) {
            Log.e("Discovery", "Failed to start discovery", e)
        }
    }

    fun stopDiscovery() {
        try {
            nsdManager.stopServiceDiscovery(discoveryListener)
        } catch (e: Exception) { }
    }
}
