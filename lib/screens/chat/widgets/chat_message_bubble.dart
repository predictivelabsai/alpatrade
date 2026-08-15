import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/chat.dart';
import 'package:alpatrade/screens/chat/widgets/responsive_markdown.dart';
import 'package:alpatrade/screens/chat/widgets/tool_execution_card.dart';

class ChatMessageBubble extends StatelessWidget {
  final ChatMessage message;

  const ChatMessageBubble({super.key, required this.message});

  bool get _isUser => message.role == 'user';

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: _isUser
            ? CrossAxisAlignment.end
            : CrossAxisAlignment.start,
        children: [
          if (!_isUser && message.agentSlug != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4, left: 4),
              child: Text(
                message.agentSlug == 'command' ? 'command' : 'AlpaTrade AI',
                style: TextStyle(
                  fontSize: 11,
                  color: AppTheme.accent,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          Container(
            constraints: BoxConstraints(
              maxWidth: _isUser
                  ? MediaQuery.sizeOf(context).width * 0.82
                  : math.min(MediaQuery.sizeOf(context).width - 32, 720),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: _isUser ? AppTheme.accent : AppTheme.bgElev,
              borderRadius: BorderRadius.only(
                topLeft: const Radius.circular(16),
                topRight: const Radius.circular(16),
                bottomLeft: Radius.circular(_isUser ? 16 : 4),
                bottomRight: Radius.circular(_isUser ? 4 : 16),
              ),
              border: _isUser
                  ? null
                  : Border.all(color: AppTheme.line, width: 0.5),
            ),
            child: _isUser
                ? Text(
                    message.content,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 14,
                      height: 1.45,
                    ),
                  )
                : ResponsiveMarkdown(data: message.content, selectable: true),
          ),
          if (message.toolCalls.isNotEmpty) ...[
            const SizedBox(height: 8),
            ...message.toolCalls.map(
              (tc) => ToolExecutionCard(toolCall: tc, isActive: false),
            ),
          ],
        ],
      ),
    );
  }
}
