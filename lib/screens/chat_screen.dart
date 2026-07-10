import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/models/chat.dart';
import 'package:carhero/providers/chat_provider.dart';
import 'package:carhero/providers/locale_provider.dart';
import 'package:carhero/providers/session_provider.dart';
import 'package:carhero/screens/chat/widgets/chat_sidebar.dart';
import 'package:carhero/screens/chat/widgets/chat_input_bar.dart';
import 'package:carhero/screens/chat/widgets/chat_message_bubble.dart';
import 'package:carhero/screens/chat/widgets/streaming_text.dart';
import 'package:carhero/screens/chat/widgets/tool_execution_card.dart';
import 'package:carhero/screens/chat/widgets/welcome_message.dart';
import 'package:carhero/screens/chat/widgets/listing_card.dart';
import 'package:share_plus/share_plus.dart';

class ChatScreen extends ConsumerStatefulWidget {
  final int? sessionId;

  const ChatScreen({super.key, this.sessionId});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final ScrollController _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    if (widget.sessionId != null) {
      _loadSession(widget.sessionId!);
    }
  }

  @override
  void didUpdateWidget(ChatScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.sessionId != oldWidget.sessionId && widget.sessionId != null) {
      _loadSession(widget.sessionId!);
    }
  }

  Future<void> _loadSession(int sessionId) async {
    try {
      final service = ref.read(sessionServiceProvider);
      final detail = await service.getSession(sessionId);
      final messages = detail.messages
          .map(
            (m) => ChatMessage(
              role: m.role,
              content: m.content,
              agentSlug: m.agentSlug,
            ),
          )
          .toList();
      ref.read(chatProvider.notifier).loadSession(sessionId, messages);
    } catch (_) {
      // Session may not exist or network error
    }
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

  void _showArtifactSheet(List<Artifact> artifacts) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        minChildSize: 0.3,
        maxChildSize: 0.9,
        builder: (ctx, scrollController) => Column(
          children: [
            Container(
              margin: const EdgeInsets.only(top: 8, bottom: 4),
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: AppTheme.gray400,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  Text(
                    'Results',
                    style: Theme.of(ctx).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${artifacts.length} item${artifacts.length == 1 ? '' : 's'}',
                    style: TextStyle(color: AppTheme.gray500, fontSize: 13),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: ListView.builder(
                controller: scrollController,
                padding: const EdgeInsets.all(12),
                itemCount: artifacts.length,
                itemBuilder: (ctx, i) {
                  final artifact = artifacts[i];
                  if (artifact.kind == 'listing' ||
                      artifact.kind == 'listings') {
                    return _buildListingArtifact(artifact);
                  }
                  return Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          if (artifact.title != null)
                            Text(
                              artifact.title!,
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                                fontSize: 14,
                              ),
                            ),
                          const SizedBox(height: 4),
                          Text(
                            artifact.kind,
                            style: TextStyle(
                              color: AppTheme.gray500,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildListingArtifact(Artifact artifact) {
    final data = artifact.data;
    // Could be a single listing or a list
    if (data.containsKey('listings')) {
      final listings = data['listings'] as List<dynamic>? ?? [];
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (artifact.title != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                artifact.title!,
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  fontSize: 15,
                ),
              ),
            ),
          ...listings.map(
            (l) => ListingCard.fromJson(l as Map<String, dynamic>),
          ),
        ],
      );
    }
    return ListingCard.fromJson(data);
  }

  Future<void> _shareSession() async {
    final sessionId = ref.read(chatProvider).currentSessionId;
    if (sessionId == null) return;
    try {
      final service = ref.read(sessionServiceProvider);
      final share = await service.shareSession(sessionId);
      if (!mounted) return;
      await SharePlus.instance.share(ShareParams(text: share.url));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Could not share: $e')));
    }
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final chatState = ref.watch(chatProvider);
    final hasMessages = chatState.messages.isNotEmpty;

    // Collect all artifacts from messages plus any streaming artifacts
    final allArtifacts = <Artifact>[
      ...chatState.artifacts,
      for (final msg in chatState.messages) ...msg.artifacts,
    ];

    // Scroll to bottom when new messages arrive
    ref.listen(chatProvider, (prev, next) {
      if (prev?.messages.length != next.messages.length ||
          prev?.streamBuffer != next.streamBuffer) {
        _scrollToBottom();
      }
    });

    return Scaffold(
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        title: Text(
          chatState.currentAgent?.name ?? 'Kenri.ai · Personal Advisor',
          overflow: TextOverflow.ellipsis,
        ),
        actions: [
          if (chatState.currentSessionId != null)
            IconButton(
              icon: const Icon(Icons.share_outlined),
              onPressed: _shareSession,
              tooltip: 'Share chat',
            ),
        ],
      ),
      drawer: const ChatSidebar(),
      body: Column(
        children: [
          Expanded(
            child: hasMessages || chatState.isStreaming
                ? _buildMessageList(chatState)
                : WelcomeMessage(
                    onPromptTap: (prompt) {
                      final lang = ref.read(localeProvider);
                      ref
                          .read(chatProvider.notifier)
                          .sendMessage(prompt, lang: lang);
                    },
                  ),
          ),
          ChatInputBar(
            isStreaming: chatState.isStreaming,
            onSend: (text) {
              final lang = ref.read(localeProvider);
              ref.read(chatProvider.notifier).sendMessage(text, lang: lang);
            },
          ),
        ],
      ),
      floatingActionButton: allArtifacts.isNotEmpty
          ? FloatingActionButton.extended(
              onPressed: () => _showArtifactSheet(allArtifacts),
              icon: const Icon(Icons.auto_awesome),
              label: Text('Results (${allArtifacts.length})'),
              backgroundColor: AppTheme.ink,
              foregroundColor: Colors.white,
            )
          : null,
      floatingActionButtonLocation: FloatingActionButtonLocation.endFloat,
    );
  }

  Widget _buildMessageList(ChatState chatState) {
    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      itemCount:
          chatState.messages.length +
          (chatState.isStreaming ? 1 : 0) +
          (chatState.error != null ? 1 : 0),
      itemBuilder: (context, index) {
        // Error card at the end
        if (chatState.error != null &&
            index ==
                chatState.messages.length + (chatState.isStreaming ? 1 : 0)) {
          return Container(
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppTheme.red600.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: AppTheme.red600.withValues(alpha: 0.3)),
            ),
            child: Row(
              children: [
                Icon(Icons.error_outline, color: AppTheme.red600, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    chatState.error!,
                    style: TextStyle(color: AppTheme.red600, fontSize: 13),
                  ),
                ),
              ],
            ),
          );
        }

        // Streaming indicator at the end
        if (chatState.isStreaming && index == chatState.messages.length) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Show active tool calls during streaming
              for (final tool in chatState.activeToolCalls)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: ToolExecutionCard(
                    toolCall: tool,
                    isActive: tool.output == null,
                  ),
                ),
              // Show streaming text
              if (chatState.streamBuffer.isNotEmpty)
                StreamingText(text: chatState.streamBuffer),
              // Show loading indicator when no content yet
              if (chatState.streamBuffer.isEmpty &&
                  chatState.activeToolCalls.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      SizedBox(width: 8),
                      Text(
                        'Thinking...',
                        style: TextStyle(fontSize: 13, color: Colors.grey),
                      ),
                    ],
                  ),
                ),
            ],
          );
        }

        // Regular message bubble
        final message = chatState.messages[index];
        return ChatMessageBubble(message: message);
      },
    );
  }
}
