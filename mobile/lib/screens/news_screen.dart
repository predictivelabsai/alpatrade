import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:alpatrade/config/constants.dart';
import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/providers/market_provider.dart';
import 'package:alpatrade/widgets/empty_state.dart';
import 'package:alpatrade/widgets/error_view.dart';

class NewsScreen extends ConsumerStatefulWidget {
  const NewsScreen({super.key});

  @override
  ConsumerState<NewsScreen> createState() => _NewsScreenState();
}

class _NewsScreenState extends ConsumerState<NewsScreen> {
  /// null = All symbols.
  String? _symbol;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(newsProvider(_symbol));

    return Scaffold(
      appBar: AppBar(title: const Text('Market news')),
      body: Column(
        children: [
          _SymbolFilter(
            selected: _symbol,
            onSelected: (s) => setState(() => _symbol = s),
          ),
          Divider(height: 1, thickness: 1, color: AppTheme.line),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () => ref.refresh(newsProvider(_symbol).future),
              color: AppTheme.accent,
              child: async.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (e, _) => ListView(
                  children: [
                    const SizedBox(height: 120),
                    ErrorView(
                      title: 'Could not load news',
                      message: '$e',
                      onRetry: () => ref.invalidate(newsProvider(_symbol)),
                    ),
                  ],
                ),
                data: (result) {
                  if (result.trim().isEmpty) {
                    return ListView(
                      children: const [
                        SizedBox(height: 120),
                        EmptyState(
                          icon: Icons.article_outlined,
                          title: 'No news',
                          subtitle: 'No headlines available right now.',
                        ),
                      ],
                    );
                  }
                  return ListView(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
                    children: [
                      MarkdownBody(
                        data: result,
                        selectable: true,
                        styleSheet: marketMarkdownStyle(),
                        onTapLink: (text, href, title) {
                          if (href != null) {
                            launchUrl(
                              Uri.parse(href),
                              mode: LaunchMode.externalApplication,
                            );
                          }
                        },
                      ),
                    ],
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SymbolFilter extends StatelessWidget {
  final String? selected;
  final ValueChanged<String?> onSelected;

  const _SymbolFilter({required this.selected, required this.onSelected});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 52,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        children: [
          ChoiceChip(
            label: const Text('All'),
            selected: selected == null,
            onSelected: (_) => onSelected(null),
          ),
          const SizedBox(width: 8),
          for (final s in AppConstants.popularSymbols) ...[
            ChoiceChip(
              label: Text(
                s,
                style: const TextStyle(fontFamily: AppTheme.monoFont),
              ),
              selected: selected == s,
              onSelected: (_) => onSelected(s),
            ),
            const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }
}

/// Shared forest-green markdown style for the market data screens.
MarkdownStyleSheet marketMarkdownStyle() => MarkdownStyleSheet(
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
