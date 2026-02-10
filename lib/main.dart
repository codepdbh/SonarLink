import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String _historyKey = 'saved_hosts';
const String _lastHostKey = 'last_host';
const String _lastPortKey = 'last_port';
const int _maxHistory = 8;

void main() {
  runApp(const SonarLinkApp());
}

class SonarLinkApp extends StatelessWidget {
  const SonarLinkApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SonarLink',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF00B4A0),
          brightness: Brightness.dark,
        ),
      ),
      home: const SonarLinkPage(),
    );
  }
}

class SonarLinkPage extends StatefulWidget {
  const SonarLinkPage({super.key});

  @override
  State<SonarLinkPage> createState() => _SonarLinkPageState();
}

class _SonarLinkPageState extends State<SonarLinkPage>
    with WidgetsBindingObserver {
  static const MethodChannel _channel = MethodChannel('audio_stream');

  final TextEditingController _ipController = TextEditingController();
  final TextEditingController _portController =
      TextEditingController(text: '5000');

  SharedPreferences? _prefs;
  List<String> _savedHosts = <String>[];
  bool _running = false;
  bool _connecting = false;
  bool _batteryOptimizationIgnored = true;
  bool _batteryCheckLoading = true;
  String _status = 'Detenido';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _channel.setMethodCallHandler(_handleNativeCall);
    _loadPreferences();
    _checkBatteryOptimization();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _checkBatteryOptimization();
    }
  }

  Future<void> _loadPreferences() async {
    final prefs = await SharedPreferences.getInstance();
    final history = prefs.getStringList(_historyKey) ?? <String>[];
    final lastHost = prefs.getString(_lastHostKey);
    final lastPort = prefs.getInt(_lastPortKey)?.toString() ?? '5000';

    if (!mounted) {
      return;
    }
    setState(() {
      _prefs = prefs;
      _savedHosts = history;
      if (lastHost != null && lastHost.isNotEmpty) {
        _ipController.text = lastHost;
      } else if (history.isNotEmpty) {
        _ipController.text = history.first;
      }
      _portController.text = lastPort;
    });
  }

  Future<void> _checkBatteryOptimization() async {
    try {
      final ignored = await _channel
              .invokeMethod<bool>('isIgnoringBatteryOptimizations') ??
          true;
      if (!mounted) {
        return;
      }
      setState(() {
        _batteryOptimizationIgnored = ignored;
        _batteryCheckLoading = false;
      });
    } on PlatformException {
      if (!mounted) {
        return;
      }
      setState(() {
        _batteryOptimizationIgnored = true;
        _batteryCheckLoading = false;
      });
    }
  }

  Future<void> _requestIgnoreBatteryOptimizations() async {
    try {
      await _channel.invokeMethod('requestIgnoreBatteryOptimizations');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Revisa los ajustes y vuelve a la app para validar el cambio.',
            ),
          ),
        );
      }
    } on PlatformException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('No se pudo abrir ajustes: ${e.message ?? e.code}'),
          ),
        );
      }
    }
    await Future<void>.delayed(const Duration(milliseconds: 700));
    if (mounted) {
      await _checkBatteryOptimization();
    }
  }

  Future<void> _handleNativeCall(MethodCall call) async {
    if (!mounted || call.method != 'status') {
      return;
    }
    final args = (call.arguments as Map?)?.cast<String, dynamic>() ?? {};
    final state = args['state'] as String? ?? '';
    final message = args['message'] as String?;
    setState(() {
      switch (state) {
        case 'connected':
          _running = true;
          _connecting = false;
          _status = 'Activo';
          break;
        case 'stalled':
          _running = true;
          _connecting = false;
          _status = 'Sin audio (esperando...)';
          break;
        case 'reconnecting':
          _running = false;
          _connecting = true;
          _status = 'Reconectando...';
          break;
        case 'disconnected':
          _running = false;
          _connecting = false;
          _status = 'Desconectado';
          break;
        case 'error':
          _running = false;
          _connecting = false;
          _status = 'Error: ${message ?? 'desconocido'}';
          break;
        case 'connecting':
          _connecting = true;
          _status = 'Conectando...';
          break;
        default:
          _status = message ?? _status;
      }
    });
  }

  Future<void> _rememberEndpoint(String host, int port) async {
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    _prefs = prefs;
    final updated = List<String>.from(_savedHosts);
    updated.removeWhere((item) => item.toLowerCase() == host.toLowerCase());
    updated.insert(0, host);
    if (updated.length > _maxHistory) {
      updated.removeRange(_maxHistory, updated.length);
    }

    await prefs.setStringList(_historyKey, updated);
    await prefs.setString(_lastHostKey, host);
    await prefs.setInt(_lastPortKey, port);

    if (!mounted) {
      return;
    }
    setState(() {
      _savedHosts = updated;
    });
  }

  Future<void> _removeHost(String host) async {
    final updated = List<String>.from(_savedHosts)..remove(host);
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    _prefs = prefs;
    await prefs.setStringList(_historyKey, updated);

    if (!mounted) {
      return;
    }
    setState(() {
      _savedHosts = updated;
      if (_ipController.text == host) {
        _ipController.clear();
      }
    });
  }

  Future<void> _clearHistory() async {
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    _prefs = prefs;
    await prefs.remove(_historyKey);
    await prefs.remove(_lastHostKey);

    if (!mounted) {
      return;
    }
    setState(() {
      _savedHosts = <String>[];
      _ipController.clear();
    });
  }

  bool _isHostValid(String host) {
    if (host.isEmpty) {
      return false;
    }
    if (InternetAddress.tryParse(host) != null) {
      return true;
    }
    return RegExp(r'^[a-zA-Z0-9.-]+$').hasMatch(host);
  }

  Future<void> _start() async {
    final host = _ipController.text.trim();
    final port = int.tryParse(_portController.text.trim()) ?? -1;

    if (!_isHostValid(host) || port <= 0 || port > 65535) {
      setState(() {
        _status = 'IP o puerto invalido';
      });
      return;
    }

    setState(() {
      _status = 'Conectando...';
      _connecting = true;
    });

    try {
      await _channel.invokeMethod('start', {'host': host, 'port': port});
      await _rememberEndpoint(host, port);
      if (!mounted) {
        return;
      }

    } on PlatformException catch (e) {
      setState(() {
        _running = false;
        _connecting = false;
        _status = 'Error: ${e.message ?? e.code}';
      });
    }
  }

  Future<void> _stop() async {
    try {
      await _channel.invokeMethod('stop');
    } catch (_) {}
    setState(() {
      _running = false;
      _connecting = false;
      _status = 'Detenido';
    });
  }

  Color _statusColor() {
    if (_running) {
      return const Color(0xFF3AF2C8);
    }
    if (_status.startsWith('Sin audio')) {
      return const Color(0xFFFFD166);
    }
    if (_connecting) {
      return const Color(0xFFFFD166);
    }
    if (_status.startsWith('Error')) {
      return const Color(0xFFFF6B6B);
    }
    return Colors.white70;
  }

  Widget _glassCard({required Widget child}) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: Colors.white.withValues(alpha: 0.16)),
      ),
      child: child,
    );
  }

  Widget _batteryCard() {
    if (_batteryCheckLoading) {
      return _glassCard(
        child: const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: <Widget>[
              SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              SizedBox(width: 10),
              Expanded(
                child: Text('Verificando optimizacion de bateria...'),
              ),
            ],
          ),
        ),
      );
    }

    if (_batteryOptimizationIgnored) {
      return _glassCard(
        child: const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: <Widget>[
              Icon(Icons.battery_charging_full_rounded, color: Color(0xFF3AF2C8)),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Optimizacion de bateria: desactivada para SonarLink',
                  style: TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
        ),
      );
    }

    return _glassCard(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            const Row(
              children: <Widget>[
                Icon(Icons.warning_amber_rounded, color: Color(0xFFFFD166)),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Riesgo de desconexion por ahorro de bateria',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            const Text(
              'Para evitar cortes, desactiva la optimizacion de bateria para esta app.',
              style: TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              onPressed: _requestIgnoreBatteryOptimizations,
              icon: const Icon(Icons.settings_suggest_rounded),
              label: const Text('Desactivar optimizacion'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _ipController.dispose();
    _portController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final canStart = !_running && !_connecting;
    final canStop = _running || _connecting;

    return Scaffold(
      extendBody: true,
      body: Stack(
        children: <Widget>[
          Positioned.fill(
            child: DecoratedBox(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: <Color>[
                    Color(0xFF081626),
                    Color(0xFF10344A),
                    Color(0xFF0D5460),
                  ],
                ),
              ),
              child: const SizedBox.expand(),
            ),
          ),
          Positioned(
            top: -80,
            right: -40,
            child: Container(
              width: 220,
              height: 220,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: const Color(0xFF3AF2C8).withValues(alpha: 0.17),
              ),
            ),
          ),
          Positioned(
            left: -60,
            bottom: -100,
            child: Container(
              width: 260,
              height: 260,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: const Color(0xFF86B8FF).withValues(alpha: 0.12),
              ),
            ),
          ),
          SafeArea(
            child: LayoutBuilder(
              builder: (BuildContext context, BoxConstraints constraints) {
                return SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
                  child: ConstrainedBox(
                    constraints: BoxConstraints(
                      minHeight: constraints.maxHeight - 18,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: <Widget>[
                        _glassCard(
                          child: Padding(
                            padding: const EdgeInsets.all(18),
                            child: Row(
                              children: <Widget>[
                                Container(
                                  width: 58,
                                  height: 58,
                                  decoration: BoxDecoration(
                                    borderRadius: BorderRadius.circular(18),
                                    gradient: const LinearGradient(
                                      colors: <Color>[
                                        Color(0xFF3AF2C8),
                                        Color(0xFF3D9BFF),
                                      ],
                                    ),
                                  ),
                                  child: const Icon(
                                    Icons.graphic_eq_rounded,
                                    color: Colors.white,
                                    size: 34,
                                  ),
                                ),
                                const SizedBox(width: 14),
                                const Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: <Widget>[
                                      Text(
                                        'SonarLink',
                                        style: TextStyle(
                                          fontSize: 28,
                                          fontWeight: FontWeight.w800,
                                          letterSpacing: 0.3,
                                        ),
                                      ),
                                      SizedBox(height: 4),
                                      Text(
                                        'PC -> Android -> Bluetooth',
                                        style: TextStyle(
                                          fontSize: 14,
                                          color: Colors.white70,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(height: 14),
                        _glassCard(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 14,
                            ),
                            child: Row(
                              children: <Widget>[
                                Container(
                                  width: 12,
                                  height: 12,
                                  decoration: BoxDecoration(
                                    shape: BoxShape.circle,
                                    color: _statusColor(),
                                  ),
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Text(
                                    'Estado: $_status',
                                    style: const TextStyle(
                                      fontSize: 16,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(height: 14),
                        _batteryCard(),
                        const SizedBox(height: 14),
                        _glassCard(
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: <Widget>[
                                const Text(
                                  'Conexion',
                                  style: TextStyle(
                                    fontSize: 17,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                const SizedBox(height: 12),
                                TextField(
                                  controller: _ipController,
                                  keyboardType: TextInputType.url,
                                  style: const TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w600,
                                  ),
                                  decoration: InputDecoration(
                                    labelText: 'IP del PC',
                                    hintText: 'Ej: 192.168.1.50',
                                    prefixIcon: const Icon(Icons.router_rounded),
                                    filled: true,
                                    fillColor:
                                        Colors.black.withValues(alpha: 0.18),
                                    border: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(14),
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 10),
                                TextField(
                                  controller: _portController,
                                  keyboardType: TextInputType.number,
                                  decoration: InputDecoration(
                                    labelText: 'Puerto',
                                    hintText: '5000',
                                    prefixIcon: const Icon(Icons.hub_rounded),
                                    filled: true,
                                    fillColor:
                                        Colors.black.withValues(alpha: 0.18),
                                    border: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(14),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(height: 14),
                        _glassCard(
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: <Widget>[
                                const Text(
                                  'Historial de IPs',
                                  style: TextStyle(
                                    fontSize: 17,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                const SizedBox(height: 12),
                                if (_savedHosts.isEmpty)
                                  const Text(
                                    'Aun no hay IPs guardadas.',
                                    style: TextStyle(color: Colors.white70),
                                  )
                                else
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 8,
                                    children: _savedHosts
                                        .map(
                                          (String host) => InputChip(
                                            label: Text(host),
                                            onPressed: () {
                                              setState(() {
                                                _ipController.text = host;
                                              });
                                            },
                                            onDeleted: () => _removeHost(host),
                                            deleteIcon: const Icon(Icons.close),
                                            selected:
                                                _ipController.text.trim() == host,
                                            selectedColor: const Color(
                                              0xFF2A5562,
                                            ).withValues(alpha: 0.9),
                                            backgroundColor: Colors.black
                                                .withValues(alpha: 0.24),
                                            side: BorderSide(
                                              color: Colors.white.withValues(
                                                alpha: 0.22,
                                              ),
                                            ),
                                          ),
                                        )
                                        .toList(),
                                  ),
                                if (_savedHosts.isNotEmpty) ...<Widget>[
                                  const SizedBox(height: 10),
                                  TextButton.icon(
                                    onPressed: _clearHistory,
                                    icon: const Icon(Icons.delete_sweep_rounded),
                                    label: const Text('Limpiar historial'),
                                  ),
                                ],
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(height: 14),
                        Row(
                          children: <Widget>[
                            Expanded(
                              child: FilledButton.icon(
                                onPressed: canStart ? _start : null,
                                style: FilledButton.styleFrom(
                                  backgroundColor: const Color(0xFF2DE0B8),
                                  foregroundColor: const Color(0xFF062528),
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 16),
                                ),
                                icon: const Icon(Icons.play_arrow_rounded),
                                label: const Text(
                                  'Conectar',
                                  style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 16,
                                  ),
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: OutlinedButton.icon(
                                onPressed: canStop ? _stop : null,
                                style: OutlinedButton.styleFrom(
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 16),
                                  side: BorderSide(
                                    color: Colors.white.withValues(alpha: 0.48),
                                  ),
                                ),
                                icon: const Icon(Icons.stop_rounded),
                                label: const Text(
                                  'Detener',
                                  style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 16,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        Text(
                          'Tip: toca una IP guardada para rellenar rapido.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.72),
                            fontSize: 13,
                          ),
                        ),
                        const SizedBox(height: 22),
                        Text(
                          'Desarrollado por Ing Paulo Daniel Batuani Hurtado y codex 5.3',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.74),
                            fontSize: 12,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                        const SizedBox(height: 8),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
