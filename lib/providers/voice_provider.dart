import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/providers/chat_provider.dart';
import 'package:alpatrade/services/voice_service.dart';

enum VoicePhase { idle, connecting, listening, thinking, speaking, error }

class VoiceUiState {
  final VoicePhase phase;
  final String label;
  final String? error;

  const VoiceUiState({
    this.phase = VoicePhase.idle,
    this.label = '',
    this.error,
  });

  bool get isActive => phase != VoicePhase.idle && phase != VoicePhase.error;

  VoiceUiState copyWith({VoicePhase? phase, String? label, String? error}) =>
      VoiceUiState(
        phase: phase ?? this.phase,
        label: label ?? this.label,
        error: error,
      );
}

final voiceServiceProvider = Provider<VoiceService>((ref) {
  final svc = VoiceService();
  ref.onDispose(svc.dispose);
  return svc;
});

final voiceProvider = NotifierProvider<VoiceNotifier, VoiceUiState>(
  VoiceNotifier.new,
);

class VoiceNotifier extends Notifier<VoiceUiState> {
  StreamSubscription<VoiceEvent>? _sub;

  @override
  VoiceUiState build() {
    ref.onDispose(() => _sub?.cancel());
    return const VoiceUiState();
  }

  Future<void> toggle() async {
    if (state.isActive) {
      await stop();
    } else {
      await start();
    }
  }

  Future<void> start() async {
    final svc = ref.read(voiceServiceProvider);
    state = const VoiceUiState(
      phase: VoicePhase.connecting,
      label: 'Connecting…',
    );
    _sub ??= svc.events.listen(_onEvent);
    final ok = await svc.start();
    if (!ok) {
      state = const VoiceUiState(
        phase: VoicePhase.error,
        label: 'Mic blocked',
        error: 'Allow microphone access and tap the mic again.',
      );
    }
  }

  Future<void> stop() async {
    await ref.read(voiceServiceProvider).stop();
    await _sub?.cancel();
    _sub = null;
    state = const VoiceUiState();
  }

  void _onEvent(VoiceEvent e) {
    final chat = ref.read(chatProvider.notifier);
    switch (e.type) {
      case 'ready':
        state = state.copyWith(
          phase: VoicePhase.listening,
          label: 'Listening…',
        );
      case 'speech_started':
        state = state.copyWith(
          phase: VoicePhase.listening,
          label: 'Listening…',
        );
      case 'speech_stopped':
        state = state.copyWith(phase: VoicePhase.thinking, label: 'Thinking…');
      case 'tool':
        state = state.copyWith(phase: VoicePhase.thinking, label: 'Checking…');
      case 'user_partial':
        if ((e.text ?? '').isNotEmpty) chat.voiceUserPartial(e.text!);
      case 'user_transcript':
        chat.voiceUserFinal(e.text ?? '');
      case 'assistant_delta':
        state = state.copyWith(phase: VoicePhase.speaking, label: 'Speaking…');
        if ((e.text ?? '').isNotEmpty) chat.voiceAssistantDelta(e.text!);
      case 'assistant_done':
        chat.voiceAssistantFinal(e.text);
      case 'done':
        state = state.copyWith(
          phase: VoicePhase.listening,
          label: 'Listening…',
        );
      case 'error':
        state = VoiceUiState(
          phase: VoicePhase.error,
          label: 'Voice error',
          error: e.message ?? 'unknown',
        );
    }
  }
}
