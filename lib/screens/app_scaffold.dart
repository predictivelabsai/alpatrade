import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/providers/connectivity_provider.dart';

class AppScaffold extends ConsumerWidget {
  final Widget child;

  const AppScaffold({super.key, required this.child});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final connectivityAsync = ref.watch(connectivityProvider);
    final isOnline = connectivityAsync.whenOrNull(data: (v) => v) ?? true;

    if (isOnline) return child;

    return Column(
      children: [
        MaterialBanner(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          content: Text(
            'No internet connection',
            style: TextStyle(fontSize: 13, color: AppTheme.gray500),
          ),
          leading: Icon(Icons.wifi_off, size: 20, color: AppTheme.gray500),
          backgroundColor: AppTheme.gray100,
          actions: const [SizedBox.shrink()],
        ),
        Expanded(child: child),
      ],
    );
  }
}
