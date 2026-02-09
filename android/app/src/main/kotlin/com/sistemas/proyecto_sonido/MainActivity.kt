package com.sistemas.proyecto_sonido

import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.BufferedInputStream
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.max

class MainActivity : FlutterActivity() {
    private val channelName = "audio_stream"
    private lateinit var methodChannel: MethodChannel
    private var streamer: AudioStreamer? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        methodChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
        methodChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "start" -> {
                    val host = call.argument<String>("host")
                    val port = call.argument<Int>("port")
                    if (host.isNullOrBlank() || port == null || port <= 0 || port > 65535) {
                        result.error("BAD_ARGS", "Host o puerto invalido", null)
                        return@setMethodCallHandler
                    }
                    if (!isWifiConnected()) {
                        result.error("NO_WIFI", "Sin conexion Wi-Fi", null)
                        return@setMethodCallHandler
                    }
                    if (streamer == null) {
                        streamer = AudioStreamer(::sendStatus)
                    }
                    try {
                        streamer?.start(host, port)
                        result.success(true)
                    } catch (e: Exception) {
                        result.error("START_FAILED", e.message, null)
                    }
                }
                "stop" -> {
                    streamer?.stop()
                    result.success(true)
                }
                "isIgnoringBatteryOptimizations" -> {
                    result.success(isBatteryOptimizationIgnored())
                }
                "requestIgnoreBatteryOptimizations" -> {
                    if (openBatteryOptimizationSettings()) {
                        result.success(true)
                    } else {
                        result.error("BATTERY_SETTINGS_FAILED", "No se pudo abrir ajustes", null)
                    }
                }
                else -> result.notImplemented()
            }
        }
    }

    override fun onDestroy() {
        streamer?.stop()
        super.onDestroy()
    }

    private fun sendStatus(state: String, message: String? = null) {
        if (!::methodChannel.isInitialized) {
            return
        }
        val payload = HashMap<String, Any>()
        payload["state"] = state
        if (message != null) {
            payload["message"] = message
        }
        runOnUiThread {
            methodChannel.invokeMethod("status", payload)
        }
    }

    private fun isWifiConnected(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val network = cm.activeNetwork ?: return false
            val caps = cm.getNetworkCapabilities(network) ?: return false
            return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        }
        @Suppress("DEPRECATION")
        val info = cm.activeNetworkInfo
        @Suppress("DEPRECATION")
        return info != null && info.isConnected && info.type == ConnectivityManager.TYPE_WIFI
    }

    private fun isBatteryOptimizationIgnored(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return true
        }
        val powerManager = getSystemService(Context.POWER_SERVICE) as? PowerManager ?: return true
        return powerManager.isIgnoringBatteryOptimizations(packageName)
    }

    private fun openBatteryOptimizationSettings(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return true
        }
        return try {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:$packageName")
            }
            startActivity(intent)
            true
        } catch (_: Exception) {
            try {
                val fallbackIntent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                startActivity(fallbackIntent)
                true
            } catch (_: Exception) {
                false
            }
        }
    }
}

private class AudioStreamer(
    private val status: (String, String?) -> Unit,
) {
    private val running = AtomicBoolean(false)
    @Volatile private var socket: Socket? = null

    fun start(host: String, port: Int) {
        if (!running.compareAndSet(false, true)) {
            return
        }

        val connectedLatch = CountDownLatch(1)
        val startError = AtomicReference<Exception?>(null)
        val startSignaled = AtomicBoolean(false)
        fun signalStart(error: Exception?) {
            if (startSignaled.compareAndSet(false, true)) {
                if (error != null) {
                    startError.set(error)
                }
                connectedLatch.countDown()
            }
        }

        val worker = Thread {
            var localSocket: Socket? = null
            var audioTrack: AudioTrack? = null
            var connected = false

            try {
                status("connecting", null)
                localSocket = Socket()
                localSocket.tcpNoDelay = true
                localSocket.connect(InetSocketAddress(host, port), 5000)
                socket = localSocket

                val input = BufferedInputStream(localSocket.getInputStream())
                val header = ByteArray(16)
                if (!readFully(input, header, 16)) {
                    throw IllegalStateException("No se recibio encabezado")
                }

                val headerBuf = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN)
                val magicBytes = ByteArray(4)
                headerBuf.get(magicBytes)
                val magic = String(magicBytes, Charsets.US_ASCII)
                if (magic != "PCM1") {
                    throw IllegalStateException("Encabezado invalido")
                }

                val sampleRate = headerBuf.int
                val channels = headerBuf.short.toInt()
                val bits = headerBuf.short.toInt()
                val blockFrames = headerBuf.int
                if (bits != 16) {
                    throw IllegalStateException("Solo PCM 16-bit es compatible")
                }

                val channelConfig = if (channels == 1) {
                    AudioFormat.CHANNEL_OUT_MONO
                } else {
                    AudioFormat.CHANNEL_OUT_STEREO
                }
                val encoding = AudioFormat.ENCODING_PCM_16BIT
                val frameSize = channels * (bits / 8)
                val minBuffer = AudioTrack.getMinBufferSize(sampleRate, channelConfig, encoding)
                val desiredBuffer = max(minBuffer, blockFrames * frameSize * 4)

                val track = AudioTrack.Builder()
                    .setAudioAttributes(
                        AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                            .build()
                    )
                    .setAudioFormat(
                        AudioFormat.Builder()
                            .setEncoding(encoding)
                            .setSampleRate(sampleRate)
                            .setChannelMask(channelConfig)
                            .build()
                    )
                    .setBufferSizeInBytes(desiredBuffer)
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .build()
                audioTrack = track
                track.play()

                val buffer = ByteArray(max(blockFrames * frameSize, 4096))
                var carrySize = 0
                connected = true
                status("connected", null)
                signalStart(null)
                while (running.get()) {
                    val read = input.read(buffer, carrySize, buffer.size - carrySize)
                    if (read <= 0) {
                        break
                    }
                    val total = carrySize + read
                    val aligned = total - (total % frameSize)
                    var offset = 0
                    while (offset < aligned) {
                        val written = track.write(buffer, offset, aligned - offset)
                        if (written <= 0) {
                            break
                        }
                        offset += written
                    }
                    val leftover = total - aligned
                    if (leftover > 0) {
                        System.arraycopy(buffer, aligned, buffer, 0, leftover)
                    }
                    carrySize = leftover
                }
            } catch (e: Exception) {
                status("error", e.message ?: "Fallo de conexion")
                signalStart(e)
            } finally {
                if (!startSignaled.get()) {
                    signalStart(IllegalStateException("Conexion interrumpida"))
                }
                try {
                    audioTrack?.stop()
                } catch (_: Exception) {
                }
                try {
                    audioTrack?.release()
                } catch (_: Exception) {
                }
                try {
                    localSocket?.close()
                } catch (_: Exception) {
                }
                if (socket == localSocket) {
                    socket = null
                }
                running.set(false)
                if (connected) {
                    status("disconnected", null)
                }
            }
        }

        worker.isDaemon = true
        worker.start()

        if (!connectedLatch.await(6, TimeUnit.SECONDS)) {
            running.set(false)
            try {
                socket?.close()
            } catch (_: Exception) {
            }
            throw IllegalStateException("Tiempo de espera al conectar")
        }

        startError.get()?.let { throw it }
    }

    fun stop() {
        running.set(false)
        try {
            socket?.close()
        } catch (_: Exception) {
        }
    }

    private fun readFully(input: InputStream, buffer: ByteArray, length: Int): Boolean {
        var offset = 0
        while (offset < length) {
            val read = input.read(buffer, offset, length - offset)
            if (read < 0) {
                return false
            }
            offset += read
        }
        return true
    }
}
