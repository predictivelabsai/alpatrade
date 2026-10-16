import 'package:flutter/material.dart';
import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/chat.dart';

/// Compact chip showing a tool/data lookup the agent ran (e.g.
/// `get_alpaca_positions`). The /v2/chat stream only reports start/end, so
/// there are no args or output to expand.
class ToolExecutionCard extends StatelessWidget {
  final ToolCall toolCall;
  final bool isActive;

  const ToolExecutionCard({
    super.key,
    required this.toolCall,
    required this.isActive,
  });

  String get _displayName => toolCall.name
      .replaceAll('get_alpaca_', '')
      .replaceAll('get_', '')
      .replaceAll('_', ' ')
      .trim();

  @override
  Widget build(BuildContext context) {
    final active = isActive && !toolCall.done;
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: AppTheme.bgRaise,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: active
              ? AppTheme.accent.withValues(alpha: 0.4)
              : AppTheme.line,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (active)
            SizedBox(
              width: 13,
              height: 13,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: AppTheme.accent,
              ),
            )
          else
            Icon(Icons.check_circle, size: 14, color: AppTheme.gain),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              active ? 'Looking up $_displayName…' : _displayName,
              style: TextStyle(
                fontSize: 12,
                color: AppTheme.inkMuted,
                fontFamily: AppTheme.monoFont,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
