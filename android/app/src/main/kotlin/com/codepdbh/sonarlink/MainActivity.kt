package com.codepdbh.sonarlink

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.max

class MainActivity : FlutterActivity() {
    private val channelName = "audio_stream"
    private val micPermissionRequestCode = 3107
    private lateinit var methodChannel: MethodChannel
    private var streamer: AudioStreamer? = null
    private var micStreamer: MicStreamer? = null
    private var pendingMicPermissionResult: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        methodChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
        methodChannel.setMethodCallHandler { call, result ->
            when (call.method) {
                "start" -> {
                    val host = call.argument<String>("host")
                    val port = call.argument<Int>("port")
                    val transport = call.argument<String>("transport") ?: "wifi"
                    if (host.isNullOrBlank() || port == null || port <= 0 || port > 65535) {
                        result.error("BAD_ARGS", "Host o puerto invalido", null)
                        return@setMethodCallHandler
                    }
                    val usbMode = transport.equals("usb", ignoreCase = true) ||
                        host.equals("127.0.0.1") ||
                        host.equals("localhost", ignoreCase = true)
                    if (!usbMode && !isWifiConnected()) {
                        result.error("NO_WIFI", "Sin conexion Wi-Fi", null)
                        return@setMethodCallHandler
                    }
                    if (streamer == null) {
                        streamer = AudioStreamer(::sendStatus)
                    }
                    streamer?.start(host, port)
                    result.success(true)
                }
                "stop" -> {
                    streamer?.stop()
                    result.success(true)
                }
                "startMic" -> {
                    val host = call.argument<String>("host")
                    val port = call.argument<Int>("port")
                    val transport = call.argument<String>("transport") ?: "wifi"
                    if (host.isNullOrBlank() || port == null || port <= 0 || port > 65535) {
                        result.error("BAD_ARGS", "Host o puerto invalido", null)
                        return@setMethodCallHandler
                    }
                    val usbMode = transport.equals("usb", ignoreCase = true) ||
                        host.equals("127.0.0.1") ||
                        host.equals("localhost", ignoreCase = true)
                    if (!usbMode && !isWifiConnected()) {
                        result.error("NO_WIFI", "Sin conexion Wi-Fi", null)
                        return@setMethodCallHandler
                    }
                    if (!hasMicPermission()) {
                        result.error("MIC_PERMISSION", "Permiso de microfono requerido", null)
                        return@setMethodCallHandler
                    }
                    if (micStreamer == null) {
                        micStreamer = MicStreamer(::sendMicStatus)
                    }
                    micStreamer?.start(host, port)
                    result.success(true)
                }
                "stopMic" -> {
                    micStreamer?.stop()
                    result.success(true)
                }
                "hasMicPermission" -> {
                    result.success(hasMicPermission())
                }
                "requestMicPermission" -> {
                    requestMicPermission(result)
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
        micStreamer?.stop()
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

    private fun sendMicStatus(state: String, message: String? = null) {
        if (!::methodChannel.isInitialized) {
            return
        }
        val payload = HashMap<String, Any>()
        payload["state"] = state
        if (message != null) {
            payload["message"] = message
        }
        runOnUiThread {
            methodChannel.invokeMethod("micStatus", payload)
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

    private fun hasMicPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestMicPermission(result: MethodChannel.Result) {
        if (hasMicPermission()) {
            result.success(true)
            return
        }
        if (pendingMicPermissionResult != null) {
            result.error("MIC_PERMISSION_PENDING", "Ya hay una solicitud de permiso en curso", null)
            return
        }
        pendingMicPermissionResult = result
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.RECORD_AUDIO),
            micPermissionRequestCode,
        )
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != micPermissionRequestCode) {
            return
        }
        val pending = pendingMicPermissionResult ?: return
        pendingMicPermissionResult = null
        val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        pending.success(granted)
    }
}

private class AudioStreamer(
    private val status: (String, String?) -> Unit,
) {
    private class RecoverableStreamException(message: String) : RuntimeException(message)
    private data class StreamResult(
        val hadConnection: Boolean,
        val errorMessage: String? = null,
    )

    companion object {
        private const val SOCKET_READ_TIMEOUT_MS = 5000
        private const val MAX_STALL_TIMEOUTS = 6
        private const val MAX_RETRIES_AFTER_CONNECTED = 8
    }

    private val active = AtomicBoolean(false)
    @Volatile private var socket: Socket? = null
    @Volatile private var worker: Thread? = null

    @Synchronized
    fun start(host: String, port: Int) {
        val currentWorker = worker
        if (active.get() && currentWorker != null && currentWorker.isAlive) {
            return
        }
        if (active.get() && (currentWorker == null || !currentWorker.isAlive)) {
            active.set(false)
        }
        if (!active.compareAndSet(false, true)) {
            return
        }

        val thread = Thread {
            try {
                var everConnected = false
                var consecutiveFailures = 0
                while (active.get()) {
                    val result = streamOnce(host, port)
                    if (result.hadConnection) {
                        everConnected = true
                    }
                    consecutiveFailures = if (result.errorMessage != null) {
                        consecutiveFailures + 1
                    } else {
                        0
                    }
                    if (active.get()) {
                        if (!everConnected) {
                            status("reconnecting", result.errorMessage)
                        } else if (result.errorMessage != null) {
                            if (consecutiveFailures >= MAX_RETRIES_AFTER_CONNECTED) {
                                status("error", "Audio inestable: ${result.errorMessage}")
                                active.set(false)
                                break
                            }
                            status("stalled", "Reintentando audio...")
                        }
                        try {
                            Thread.sleep(1000)
                        } catch (_: InterruptedException) {
                        }
                    }
                }
            } catch (t: Throwable) {
                if (active.get()) {
                    status("error", t.message ?: "Fallo interno")
                }
            } finally {
                active.set(false)
                worker = null
                try {
                    socket?.close()
                } catch (_: Exception) {
                }
                socket = null
            }
        }
        thread.isDaemon = true
        worker = thread
        thread.start()
    }

    private fun streamOnce(host: String, port: Int): StreamResult {
        var localSocket: Socket? = null
        var audioTrack: AudioTrack? = null
        var connected = false
        var stalled = false

        try {
            status("connecting", null)
            localSocket = Socket()
            localSocket.tcpNoDelay = true
            localSocket.keepAlive = true
            localSocket.soTimeout = SOCKET_READ_TIMEOUT_MS
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
            var stallTimeoutCount = 0
            connected = true
            status("connected", null)

            while (active.get()) {
                val read = try {
                    input.read(buffer, carrySize, buffer.size - carrySize)
                } catch (_: SocketTimeoutException) {
                    stallTimeoutCount += 1
                    if (!stalled) {
                        status("stalled", "Sin audio")
                        stalled = true
                    }
                    if (stallTimeoutCount >= MAX_STALL_TIMEOUTS) {
                        throw RecoverableStreamException(
                            "Sin audio por ${SOCKET_READ_TIMEOUT_MS * MAX_STALL_TIMEOUTS / 1000}s"
                        )
                    }
                    continue
                }
                if (read <= 0) {
                    throw RecoverableStreamException("Conexion cerrada")
                }
                stallTimeoutCount = 0
                if (stalled) {
                    stalled = false
                    status("connected", null)
                }
                val total = carrySize + read
                val aligned = total - (total % frameSize)
                var offset = 0
                while (offset < aligned) {
                    val written = track.write(buffer, offset, aligned - offset)
                    if (written <= 0) {
                        throw RecoverableStreamException("AudioTrack write=$written")
                    }
                    offset += written
                }
                val leftover = total - aligned
                if (leftover > 0) {
                    System.arraycopy(buffer, aligned, buffer, 0, leftover)
                }
                carrySize = leftover
            }
            return StreamResult(hadConnection = connected)
        } catch (e: RecoverableStreamException) {
            return StreamResult(hadConnection = connected, errorMessage = e.message)
        } catch (e: Exception) {
            if (!active.get()) {
                return StreamResult(hadConnection = connected)
            }
            val detail = e.message ?: e.javaClass.simpleName
            return StreamResult(hadConnection = connected, errorMessage = detail)
        } finally {
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
            if (connected && !active.get()) {
                status("disconnected", null)
            }
        }
    }

    @Synchronized
    fun stop() {
        active.set(false)
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        worker?.interrupt()
        worker = null
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

private class MicStreamer(
    private val status: (String, String?) -> Unit,
) {
    private data class StreamResult(
        val hadConnection: Boolean,
        val errorMessage: String? = null,
    )

    companion object {
        private const val MIC_MAGIC = "MIC1"
        private const val SAMPLE_RATE = 48000
        private const val CHANNELS = 1
        private const val BITS = 16
        private const val BLOCK_FRAMES = 960
        private const val MAX_INITIAL_RETRIES = 10
        private const val MAX_RETRIES_AFTER_CONNECTED = 6
    }

    private val active = AtomicBoolean(false)
    @Volatile private var socket: Socket? = null
    @Volatile private var worker: Thread? = null

    @Synchronized
    fun start(host: String, port: Int) {
        val currentWorker = worker
        if (active.get() && currentWorker != null && currentWorker.isAlive) {
            return
        }
        if (active.get() && (currentWorker == null || !currentWorker.isAlive)) {
            active.set(false)
        }
        if (!active.compareAndSet(false, true)) {
            return
        }

        val thread = Thread {
            try {
                var everConnected = false
                var consecutiveFailures = 0
                while (active.get()) {
                    val result = streamOnce(host, port)
                    if (result.hadConnection) {
                        everConnected = true
                    }
                    if (result.errorMessage != null) {
                        consecutiveFailures += 1
                    } else {
                        consecutiveFailures = 0
                    }
                    if (active.get()) {
                        if (!everConnected && consecutiveFailures >= MAX_INITIAL_RETRIES) {
                            val detail = result.errorMessage ?: "sin respuesta del servidor de microfono"
                            status("error", "Mic bridge no disponible: $detail")
                            active.set(false)
                            break
                        }
                        if (everConnected && consecutiveFailures >= MAX_RETRIES_AFTER_CONNECTED) {
                            val detail = result.errorMessage ?: "conexion perdida"
                            status("error", "Mic inestable: $detail. Revisa Mic bridge/USB.")
                            active.set(false)
                            break
                        }
                        status("reconnecting", result.errorMessage)
                        val backoffMs = minOf(1000L * maxOf(1, consecutiveFailures), 5000L)
                        try {
                            Thread.sleep(backoffMs)
                        } catch (_: InterruptedException) {
                        }
                    }
                }
            } catch (t: Throwable) {
                if (active.get()) {
                    status("error", t.message ?: "Fallo interno")
                }
            } finally {
                active.set(false)
                worker = null
                try {
                    socket?.close()
                } catch (_: Exception) {
                }
                socket = null
            }
        }
        thread.isDaemon = true
        worker = thread
        thread.start()
    }

    private fun streamOnce(host: String, port: Int): StreamResult {
        var localSocket: Socket? = null
        var audioRecord: AudioRecord? = null
        var connected = false

        try {
            status("connecting", null)
            localSocket = Socket()
            localSocket.tcpNoDelay = true
            localSocket.keepAlive = true
            localSocket.connect(InetSocketAddress(host, port), 5000)
            socket = localSocket

            val output = BufferedOutputStream(localSocket.getOutputStream())
            val header = ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN)
            header.put(MIC_MAGIC.toByteArray(Charsets.US_ASCII))
            header.putInt(SAMPLE_RATE)
            header.putShort(CHANNELS.toShort())
            header.putShort(BITS.toShort())
            header.putInt(BLOCK_FRAMES)
            output.write(header.array())
            output.flush()

            val channelConfig = AudioFormat.CHANNEL_IN_MONO
            val encoding = AudioFormat.ENCODING_PCM_16BIT
            val minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, channelConfig, encoding)
            if (minBuffer <= 0) {
                throw IllegalStateException("No se pudo inicializar AudioRecord")
            }
            val desiredBuffer = max(minBuffer, BLOCK_FRAMES * CHANNELS * (BITS / 8) * 4)
            val record = AudioRecord(
                MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                SAMPLE_RATE,
                channelConfig,
                encoding,
                desiredBuffer,
            )
            if (record.state != AudioRecord.STATE_INITIALIZED) {
                throw IllegalStateException("AudioRecord no inicializado")
            }
            audioRecord = record

            val frameBytes = CHANNELS * (BITS / 8)
            val packet = ByteArray(max(BLOCK_FRAMES * frameBytes, 1920))

            record.startRecording()
            connected = true
            status("connected", null)

            while (active.get()) {
                val read = record.read(packet, 0, packet.size)
                if (read > 0) {
                    output.write(packet, 0, read)
                    output.flush()
                } else if (read < 0) {
                    throw IllegalStateException("Error de captura de microfono: $read")
                }
            }
            return StreamResult(hadConnection = connected)
        } catch (e: Exception) {
            if (!active.get()) {
                return StreamResult(hadConnection = connected)
            }
            val detail = e.message ?: e.javaClass.simpleName
            return StreamResult(hadConnection = connected, errorMessage = detail)
        } finally {
            try {
                audioRecord?.stop()
            } catch (_: Exception) {
            }
            try {
                audioRecord?.release()
            } catch (_: Exception) {
            }
            try {
                localSocket?.close()
            } catch (_: Exception) {
            }
            if (socket == localSocket) {
                socket = null
            }
            if (connected) {
                status("disconnected", null)
            }
        }
    }

    @Synchronized
    fun stop() {
        active.set(false)
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        worker?.interrupt()
        worker = null
    }
}
