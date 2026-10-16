import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_pcm_sound/flutter_pcm_sound.dart';
import 'package:record/record.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'package:alpatrade/config/api_config.dart';

/// One decoded event from the /ws/voice proxy.
class VoiceEvent {
  final String type;
  final String? text;
  final String? name;
  final String? message;

  const VoiceEvent(this.type, {this.text, this.name, this.message});
}

/// Bridges the device mic and speaker to the AlpaTrade x.ai realtime voice
/// proxy (wss://…/ws/voice, PCM16 mono @ 24 kHz, server-side VAD).
///
/// The browser reference implementation (static/voice.js) just streams mic
/// audio up and plays the agent's audio down; this mirrors that.
class VoiceService {
  static const int _rate = 24000;

  final _events = StreamController<VoiceEvent>.broadcast();
  Stream<VoiceEvent> get events => _events.stream;

  WebSocketChannel? _ws;
  final AudioRecorder _recorder = AudioRecorder();
  StreamSubscription<Uint8List>? _micSub;
  StreamSubscription? _wsSub;
  bool _pcmReady = false;
  bool _active = false;

  bool get isActive => _active;

  /// Returns false if the mic permission was denied (caller shows a message).
  Future<bool> start() async {
    if (_active) return true;

    if (!await _recorder.hasPermission()) {
      _emit(const VoiceEvent('error', message: 'Microphone permission denied'));
      return false;
    }

    _active = true;

    // Speaker: streamed PCM16 playback.
    try {
      await FlutterPcmSound.setup(sampleRate: _rate, channelCount: 1);
      FlutterPcmSound.setFeedThreshold(_rate ~/ 10); // ~100 ms
      _pcmReady = true;
    } catch (e) {
      _pcmReady = false; // transcript still works without playback
    }

    // WebSocket to the voice proxy.
    _ws = WebSocketChannel.connect(Uri.parse(ApiConfig.voiceWsUrl));
    _wsSub = _ws!.stream.listen(
      _onWsData,
      onError: (e) => _emit(VoiceEvent('error', message: '$e')),
      onDone: () {
        if (_active) stop();
      },
    );

    // Mic: 24 kHz mono PCM16 stream → base64 → WS.
    final micStream = await _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: _rate,
        numChannels: 1,
        echoCancel: true,
        noiseSuppress: true,
      ),
    );
    _micSub = micStream.listen((bytes) {
      final ws = _ws;
      if (ws == null || !_active) return;
      ws.sink.add(jsonEncode({'type': 'audio', 'audio': base64Encode(bytes)}));
    });

    return true;
  }

  void _onWsData(dynamic data) {
    Map<String, dynamic> m;
    try {
      m = jsonDecode(data as String) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    final type = m['type'] as String? ?? '';
    if (type == 'audio') {
      _play(m['audio'] as String? ?? '');
      _emit(const VoiceEvent('audio'));
      return;
    }
    _emit(
      VoiceEvent(
        type,
        text: m['text'] as String?,
        name: m['name'] as String?,
        message: m['message'] as String?,
      ),
    );
  }

  void _play(String b64) {
    if (!_pcmReady || b64.isEmpty) return;
    try {
      final bytes = base64Decode(b64);
      final samples = Int16List.view(
        bytes.buffer,
        bytes.offsetInBytes,
        bytes.length ~/ 2,
      );
      FlutterPcmSound.feed(PcmArrayInt16.fromList(samples.toList()));
    } catch (_) {
      // Drop a bad frame rather than kill the session.
    }
  }

  Future<void> stop() async {
    if (!_active) return;
    _active = false;
    await _micSub?.cancel();
    _micSub = null;
    try {
      await _recorder.stop();
    } catch (_) {}
    await _wsSub?.cancel();
    _wsSub = null;
    try {
      await _ws?.sink.close();
    } catch (_) {}
    _ws = null;
    if (_pcmReady) {
      try {
        await FlutterPcmSound.release();
      } catch (_) {}
      _pcmReady = false;
    }
  }

  void _emit(VoiceEvent e) {
    if (!_events.isClosed) _events.add(e);
  }

  Future<void> dispose() async {
    await stop();
    await _recorder.dispose();
    await _events.close();
  }
}
