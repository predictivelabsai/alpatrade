import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:alpatrade/screens/chat_screen.dart';
import 'package:alpatrade/screens/portfolio_screen.dart';
import 'package:alpatrade/screens/activity_screen.dart';
import 'package:alpatrade/screens/strategies_screen.dart';
import 'package:alpatrade/screens/more_screen.dart';
import 'package:alpatrade/screens/app_scaffold.dart';

final _rootNavigatorKey = GlobalKey<NavigatorState>();
final _shellNavigatorKey = GlobalKey<NavigatorState>();

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: '/chat',
    routes: [
      // '/' just enters the chat tab (no auth, no marketing landing).
      GoRoute(
        path: '/',
        parentNavigatorKey: _rootNavigatorKey,
        redirect: (_, _) => '/chat',
      ),
      ShellRoute(
        navigatorKey: _shellNavigatorKey,
        builder: (context, state, child) => AppScaffold(child: child),
        routes: [
          GoRoute(
            path: '/chat',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: ChatScreen()),
          ),
          GoRoute(
            path: '/portfolio',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: PortfolioScreen()),
          ),
          GoRoute(
            path: '/activity',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: ActivityScreen()),
          ),
          GoRoute(
            path: '/strategies',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: StrategiesScreen()),
          ),
          GoRoute(
            path: '/more',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: MoreScreen()),
          ),
        ],
      ),
    ],
  );
});
