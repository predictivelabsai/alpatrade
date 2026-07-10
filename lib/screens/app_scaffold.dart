import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/providers/connectivity_provider.dart';

class _Tab {
  final String path;
  final IconData icon;
  final IconData activeIcon;
  final String label;
  const _Tab(this.path, this.icon, this.activeIcon, this.label);
}

const _tabs = [
  _Tab('/chat', Icons.chat_bubble_outline, Icons.chat_bubble, 'Chat'),
  _Tab('/portfolio', Icons.pie_chart_outline, Icons.pie_chart, 'Portfolio'),
  _Tab(
    '/activity',
    Icons.receipt_long_outlined,
    Icons.receipt_long,
    'Activity',
  ),
  _Tab('/strategies', Icons.insights_outlined, Icons.insights, 'Strategies'),
  _Tab('/more', Icons.more_horiz, Icons.more_horiz, 'More'),
];

class AppScaffold extends ConsumerWidget {
  final Widget child;

  const AppScaffold({super.key, required this.child});

  int _indexFor(String location) {
    final i = _tabs.indexWhere((t) => location.startsWith(t.path));
    return i < 0 ? 0 : i;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connectivityAsync = ref.watch(connectivityProvider);
    final isOnline = connectivityAsync.whenOrNull(data: (v) => v) ?? true;
    final location = GoRouterState.of(context).uri.path;
    final index = _indexFor(location);

    return Scaffold(
      body: Column(
        children: [
          if (!isOnline)
            MaterialBanner(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              content: Text(
                'No internet connection',
                style: TextStyle(fontSize: 13, color: AppTheme.inkMuted),
              ),
              leading: Icon(Icons.wifi_off, size: 20, color: AppTheme.inkMuted),
              backgroundColor: AppTheme.bgRaise,
              actions: const [SizedBox.shrink()],
            ),
          Expanded(child: child),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: index,
        onTap: (i) {
          if (i != index) context.go(_tabs[i].path);
        },
        items: [
          for (final t in _tabs)
            BottomNavigationBarItem(
              icon: Icon(t.icon),
              activeIcon: Icon(t.activeIcon),
              label: t.label,
            ),
        ],
      ),
    );
  }
}
