import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/providers/voice_provider.dart';

/// Voice status strip shown above the composer while a voice session is active.
/// Mirrors the alpatrade web voice bar: an animated 5-bar waveform + status +
/// "End voice", colored per state (listening=blue, speaking=green,
/// thinking=amber, error=red).
class VoicePanel extends ConsumerWidget {
  const VoicePanel({super.key});

  static const _blue = Color(0xFF2563EB);
  static const _amber = Color(0xFFF59E0B);

  static Color _colorFor(VoicePhase phase) => switch (phase) {
    VoicePhase.listening => _blue,
    VoicePhase.speaking => AppTheme.accent,
    VoicePhase.thinking => _amber,
    VoicePhase.error => AppTheme.loss,
    VoicePhase.connecting => _blue,
    VoicePhase.idle => AppTheme.inkDim,
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final voice = ref.watch(voiceProvider);
    if (voice.phase == VoicePhase.idle) return const SizedBox.shrink();

    final color = _colorFor(voice.phase);
    final isError = voice.phase == VoicePhase.error;
    final animate =
        voice.phase == VoicePhase.listening ||
        voice.phase == VoicePhase.speaking ||
        voice.phase == VoicePhase.thinking;

    return Container(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.7), width: 0.8),
      ),
      child: Row(
        children: [
          _Waveform(color: color, animate: animate),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  voice.label.isEmpty ? 'Voice' : voice.label,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: color,
                  ),
                ),
                if (voice.error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      voice.error!,
                      style: TextStyle(fontSize: 11, color: AppTheme.inkMuted),
                    ),
                  ),
              ],
            ),
          ),
          TextButton(
            onPressed: () => ref.read(voiceProvider.notifier).stop(),
            style: TextButton.styleFrom(
              foregroundColor: color,
              padding: const EdgeInsets.symmetric(horizontal: 8),
              minimumSize: const Size(0, 32),
            ),
            child: Text(isError ? 'Dismiss' : 'End voice'),
          ),
        ],
      ),
    );
  }
}

/// Five bars bouncing between 6 and 22 px on a 1 s cycle with staggered
/// phase — the Flutter equivalent of the web `voiceBounce` keyframe.
class _Waveform extends StatefulWidget {
  final Color color;
  final bool animate;

  const _Waveform({required this.color, required this.animate});

  @override
  State<_Waveform> createState() => _WaveformState();
}

class _WaveformState extends State<_Waveform>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1000),
  );

  static const _bars = 5;
  static const _minH = 6.0;
  static const _maxH = 22.0;
  static const _delays = [0.0, 0.12, 0.24, 0.36, 0.48]; // seconds

  @override
  void initState() {
    super.initState();
    if (widget.animate) _c.repeat();
  }

  @override
  void didUpdateWidget(_Waveform old) {
    super.didUpdateWidget(old);
    if (widget.animate && !_c.isAnimating) {
      _c.repeat();
    } else if (!widget.animate && _c.isAnimating) {
      _c.stop();
      _c.value = 0;
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: _maxH,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) {
          return Row(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              for (var i = 0; i < _bars; i++) ...[
                if (i > 0) const SizedBox(width: 3),
                _bar(i),
              ],
            ],
          );
        },
      ),
    );
  }

  Widget _bar(int i) {
    final double h;
    if (widget.animate) {
      final t = (_c.value + _delays[i]) % 1.0;
      h = _minH + (_maxH - _minH) * math.sin(t * math.pi);
    } else {
      h = _minH;
    }
    return Container(
      width: 3,
      height: h,
      decoration: BoxDecoration(
        color: widget.color,
        borderRadius: BorderRadius.circular(3),
      ),
    );
  }
}
