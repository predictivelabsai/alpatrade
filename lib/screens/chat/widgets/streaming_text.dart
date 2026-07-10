import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:carhero/config/theme.dart';

class StreamingText extends StatefulWidget {
  final String text;

  const StreamingText({super.key, required this.text});

  @override
  State<StreamingText> createState() => _StreamingTextState();
}

class _StreamingTextState extends State<StreamingText>
    with SingleTickerProviderStateMixin {
  late final AnimationController _cursorController;

  @override
  void initState() {
    super.initState();
    _cursorController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _cursorController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width * 0.82,
      ),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.gray50,
        borderRadius: const BorderRadius.only(
          topLeft: Radius.circular(16),
          topRight: Radius.circular(16),
          bottomLeft: Radius.circular(4),
          bottomRight: Radius.circular(16),
        ),
        border: Border.all(color: AppTheme.gray200, width: 0.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          MarkdownBody(
            data: widget.text,
            selectable: false,
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
                        child: CircularProgressIndicator(strokeWidth: 2),
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
                backgroundColor: AppTheme.gray100,
                color: AppTheme.ink,
                fontSize: 13,
              ),
              codeblockDecoration: BoxDecoration(
                color: AppTheme.gray100,
                borderRadius: BorderRadius.circular(6),
              ),
              listBullet: TextStyle(color: AppTheme.ink, fontSize: 14),
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
          // Blinking cursor
          AnimatedBuilder(
            animation: _cursorController,
            builder: (context, child) {
              return Opacity(
                opacity: _cursorController.value,
                child: Container(
                  width: 2,
                  height: 16,
                  margin: const EdgeInsets.only(top: 2),
                  color: AppTheme.ink,
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}
