import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/models/chat.dart';
import 'package:carhero/screens/chat/widgets/tool_execution_card.dart';
import 'package:carhero/screens/chat/widgets/listing_card.dart';

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
          // Agent label for assistant messages
          if (!_isUser && message.agentSlug != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 4, left: 4),
              child: Text(
                message.agentSlug!,
                style: TextStyle(
                  fontSize: 11,
                  color: AppTheme.gray400,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),

          // Message bubble
          Container(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.82,
            ),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: _isUser ? AppTheme.ink : AppTheme.gray50,
              borderRadius: BorderRadius.only(
                topLeft: const Radius.circular(16),
                topRight: const Radius.circular(16),
                bottomLeft: Radius.circular(_isUser ? 16 : 4),
                bottomRight: Radius.circular(_isUser ? 4 : 16),
              ),
              border: _isUser
                  ? null
                  : Border.all(color: AppTheme.gray200, width: 0.5),
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
                    imageBuilder: (uri, title, alt) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: CachedNetworkImage(
                          imageUrl: uri.toString(),
                          fit: BoxFit.contain,
                          placeholder: (_, __) => Container(
                            height: 120,
                            color: AppTheme.gray100,
                            child: const Center(
                              child: SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              ),
                            ),
                          ),
                          errorWidget: (_, __, ___) => Container(
                            height: 60,
                            color: AppTheme.gray100,
                            child: Center(
                              child: Icon(
                                Icons.broken_image_outlined,
                                color: AppTheme.gray400,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    styleSheet: MarkdownStyleSheet(
                      p: TextStyle(
                        color: AppTheme.ink,
                        fontSize: 14,
                        height: 1.5,
                      ),
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
                        backgroundColor: AppTheme.gray100,
                        color: AppTheme.ink,
                        fontSize: 13,
                      ),
                      codeblockDecoration: BoxDecoration(
                        color: AppTheme.gray100,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      blockquoteDecoration: BoxDecoration(
                        border: Border(
                          left: BorderSide(color: AppTheme.gray400, width: 3),
                        ),
                      ),
                      listBullet: TextStyle(color: AppTheme.ink, fontSize: 14),
                      tableHead: TextStyle(
                        fontWeight: FontWeight.w600,
                        color: AppTheme.ink,
                      ),
                      tableBorder: TableBorder.all(
                        color: AppTheme.gray200,
                        width: 1,
                      ),
                      a: TextStyle(
                        color: AppTheme.blue600,
                        decoration: TextDecoration.underline,
                      ),
                    ),
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

          // Tool execution cards
          if (message.toolCalls.isNotEmpty) ...[
            const SizedBox(height: 8),
            ...message.toolCalls.map(
              (tc) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: ToolExecutionCard(toolCall: tc, isActive: false),
              ),
            ),
          ],

          // Inline artifacts (listings)
          if (message.artifacts.isNotEmpty) ...[
            const SizedBox(height: 8),
            ...message.artifacts.map((artifact) {
              if (artifact.kind == 'listing' || artifact.kind == 'listings') {
                return _buildListingArtifact(artifact);
              }
              return Card(
                margin: const EdgeInsets.only(bottom: 6),
                child: Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (artifact.title != null)
                        Text(
                          artifact.title!,
                          style: const TextStyle(
                            fontWeight: FontWeight.w600,
                            fontSize: 13,
                          ),
                        ),
                      const SizedBox(height: 4),
                      Text(
                        artifact.kind,
                        style: TextStyle(fontSize: 12, color: AppTheme.gray500),
                      ),
                    ],
                  ),
                ),
              );
            }),
          ],
        ],
      ),
    );
  }

  Widget _buildListingArtifact(Artifact artifact) {
    final data = artifact.data;
    if (data.containsKey('listings')) {
      final listings = data['listings'] as List<dynamic>? ?? [];
      if (listings.isEmpty) return const SizedBox.shrink();
      return SizedBox(
        height: 180,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(vertical: 4),
          itemCount: listings.length,
          separatorBuilder: (_, __) => const SizedBox(width: 8),
          itemBuilder: (ctx, i) => SizedBox(
            width: 260,
            child: ListingCard.fromJson(
              listings[i] as Map<String, dynamic>,
              compact: true,
            ),
          ),
        ),
      );
    }
    return ListingCard.fromJson(data);
  }
}
