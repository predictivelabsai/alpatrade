import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/providers/market_provider.dart';
import 'package:alpatrade/screens/news_screen.dart' show marketMarkdownStyle;
import 'package:alpatrade/widgets/empty_state.dart';
import 'package:alpatrade/widgets/error_view.dart';

class MoversScreen extends ConsumerWidget {
  const MoversScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(moversProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Market movers')),
      body: RefreshIndicator(
        onRefresh: () => ref.refresh(moversProvider.future),
        color: AppTheme.accent,
        child: async.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(
            children: [
              const SizedBox(height: 120),
              ErrorView(
                title: 'Could not load movers',
                message: '$e',
                onRetry: () => ref.invalidate(moversProvider),
              ),
            ],
          ),
          data: (result) {
            if (result.trim().isEmpty) {
              return ListView(
                children: const [
                  SizedBox(height: 120),
                  EmptyState(
                    icon: Icons.trending_up,
                    title: 'No movers',
                    subtitle: 'No market movers available right now.',
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
    );
  }
}
