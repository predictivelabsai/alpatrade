import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/chat.dart';
import 'package:alpatrade/providers/chat_provider.dart';
import 'package:alpatrade/providers/voice_provider.dart';
import 'package:alpatrade/screens/chat/widgets/chat_input_bar.dart';
import 'package:alpatrade/screens/chat/widgets/quick_order_bar.dart';
import 'package:alpatrade/screens/chat/widgets/order_ticket_sheet.dart';
import 'package:alpatrade/screens/chat/widgets/chat_message_bubble.dart';
import 'package:alpatrade/screens/chat/widgets/streaming_text.dart';
import 'package:alpatrade/screens/chat/widgets/tool_execution_card.dart';
import 'package:alpatrade/screens/chat/widgets/voice_panel.dart';
import 'package:alpatrade/screens/chat/widgets/welcome_message.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final ScrollController _scrollController = ScrollController();
  final TextEditingController _inputController = TextEditingController();
  final FocusNode _inputFocus = FocusNode();

  void _openOrderTicket(OrderPreset preset) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) =>
          OrderTicketSheet(side: preset.side, orderType: preset.orderType),
    );
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  void dispose() {
    _scrollController.dispose();
    _inputController.dispose();
    _inputFocus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final chatState = ref.watch(chatProvider);
    final voice = ref.watch(voiceProvider);
    final hasContent =
        chatState.messages.isNotEmpty ||
        chatState.isStreaming ||
        chatState.liveUserText != null ||
        chatState.liveAssistantText != null;

    ref.listen(chatProvider, (prev, next) {
      if (prev?.messages.length != next.messages.length ||
          prev?.streamBuffer != next.streamBuffer ||
          prev?.liveUserText != next.liveUserText ||
          prev?.liveAssistantText != next.liveAssistantText) {
        _scrollToBottom();
      }
    });

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Icon(Icons.candlestick_chart, size: 20, color: AppTheme.accent),
            const SizedBox(width: 8),
            const Text('AlpaTrade'),
          ],
        ),
        actions: [
          if (chatState.messages.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.add_comment_outlined),
              tooltip: 'New chat',
              onPressed: () => ref.read(chatProvider.notifier).newChat(),
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: hasContent
                ? _buildMessageList(chatState)
                : WelcomeMessage(
                    onPromptTap: (prompt) =>
                        ref.read(chatProvider.notifier).sendMessage(prompt),
                  ),
          ),
          const VoicePanel(),
          QuickOrderBar(onSelect: _openOrderTicket),
          ChatInputBar(
            isStreaming: chatState.isStreaming,
            voiceActive: voice.isActive,
            controller: _inputController,
            focusNode: _inputFocus,
            onSend: (text) => ref.read(chatProvider.notifier).sendMessage(text),
            onMic: () => ref.read(voiceProvider.notifier).toggle(),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageList(ChatState chatState) {
    final items = <Widget>[
      for (final m in chatState.messages) ChatMessageBubble(message: m),
    ];

    // Text-chat streaming (tools + partial answer).
    if (chatState.isStreaming) {
      items.add(
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final tool in chatState.activeToolCalls)
              ToolExecutionCard(toolCall: tool, isActive: !tool.done),
            if (chatState.streamBuffer.isNotEmpty)
              StreamingText(text: chatState.streamBuffer),
            if (chatState.streamBuffer.isEmpty &&
                chatState.activeToolCalls.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Row(
                  children: [
                    SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: AppTheme.accent,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      'Thinking…',
                      style: TextStyle(fontSize: 13, color: AppTheme.inkDim),
                    ),
                  ],
                ),
              ),
          ],
        ),
      );
    }

    // Live voice transcript — user speech, then the agent typing its reply back.
    if (chatState.liveUserText != null) {
      items.add(
        ChatMessageBubble(
          message: ChatMessage(role: 'user', content: chatState.liveUserText!),
        ),
      );
    }
    if (chatState.liveAssistantText != null) {
      items.add(StreamingText(text: chatState.liveAssistantText!));
    }

    if (chatState.error != null) {
      items.add(_ErrorCard(message: chatState.error!));
    }

    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      itemCount: items.length,
      itemBuilder: (context, index) => items[index],
    );
  }
}

class _ErrorCard extends StatelessWidget {
  final String message;
  const _ErrorCard({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.loss.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppTheme.loss.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline, color: AppTheme.loss, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: TextStyle(color: AppTheme.loss, fontSize: 13),
            ),
          ),
        ],
      ),
    );
  }
}
