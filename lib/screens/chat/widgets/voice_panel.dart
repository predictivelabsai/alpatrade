import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/providers/voice_provider.dart';

/// Slim voice status strip shown above the input bar while a voice session is
/// active. Mirrors the web voice.js panel (orb + status + End button).
class VoicePanel extends ConsumerWidget {
  const VoicePanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final voice = ref.watch(voiceProvider);
    if (voice.phase == VoicePhase.idle) return const SizedBox.shrink();

    final isError = voice.phase == VoicePhase.error;

    return Container(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: isError
            ? AppTheme.loss.withValues(alpha: 0.08)
            : AppTheme.accentDim.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isError ? AppTheme.loss : AppTheme.accent,
          width: 0.6,
        ),
      ),
      child: Row(
        children: [
          _Orb(phase: voice.phase),
          const SizedBox(width: 10),
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
                    color: isError ? AppTheme.loss : AppTheme.accentDeep,
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
              foregroundColor: isError ? AppTheme.loss : AppTheme.accentDeep,
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

class _Orb extends StatefulWidget {
  final VoicePhase phase;
  const _Orb({required this.phase});

  @override
  State<_Orb> createState() => _OrbState();
}

class _OrbState extends State<_Orb> with SingleTickerProviderStateMixin {
  late final AnimationController _c;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = switch (widget.phase) {
      VoicePhase.error => AppTheme.loss,
      VoicePhase.speaking => AppTheme.accent,
      VoicePhase.thinking => AppTheme.accentDeep,
      _ => AppTheme.accent,
    };
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final pulse =
            widget.phase == VoicePhase.connecting ||
                widget.phase == VoicePhase.error
            ? 1.0
            : 0.55 + _c.value * 0.45;
        return Container(
          width: 14,
          height: 14,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: color.withValues(alpha: pulse),
          ),
        );
      },
    );
  }
}
