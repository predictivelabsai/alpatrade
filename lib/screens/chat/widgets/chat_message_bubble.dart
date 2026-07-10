import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/chat.dart';
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
              maxWidth: MediaQuery.of(context).size.width * 0.82,
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
                : MarkdownBody(
                    data: message.content,
                    selectable: true,
                    styleSheet: _markdownStyle(context),
                    onTapLink: (text, href, title) {
                      if (href != null) {
                        launchUrl(
                          Uri.parse(href),
                          mode: LaunchMode.externalApplication,
                        );
                      }
                    },
                  ),
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

  MarkdownStyleSheet _markdownStyle(BuildContext context) => MarkdownStyleSheet(
    p: TextStyle(color: AppTheme.ink, fontSize: 14, height: 1.5),
    h1: TextStyle(
      color: AppTheme.ink,
      fontSize: 20,
      fontWeight: FontWeight.w700,
      height: 1.3,
    ),
    h2: TextStyle(
      color: AppTheme.ink,
      fontSize: 17,
      fontWeight: FontWeight.w600,
      height: 1.3,
    ),
    h3: TextStyle(
      color: AppTheme.ink,
      fontSize: 15,
      fontWeight: FontWeight.w600,
      height: 1.3,
    ),
    code: TextStyle(
      backgroundColor: AppTheme.bgRaise,
      color: AppTheme.accentDeep,
      fontFamily: AppTheme.monoFont,
      fontSize: 13,
    ),
    codeblockDecoration: BoxDecoration(
      color: AppTheme.bgRaise,
      borderRadius: BorderRadius.circular(6),
    ),
    blockquoteDecoration: BoxDecoration(
      border: Border(left: BorderSide(color: AppTheme.accent, width: 3)),
    ),
    listBullet: TextStyle(color: AppTheme.ink, fontSize: 14),
    tableHead: TextStyle(fontWeight: FontWeight.w600, color: AppTheme.ink),
    tableBorder: TableBorder.all(color: AppTheme.line, width: 1),
    a: TextStyle(color: AppTheme.accent, decoration: TextDecoration.underline),
  );
}
