import 'package:alpatrade/screens/research_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:alpatrade/screens/chat_screen.dart';
import 'package:alpatrade/screens/auth_screen.dart';
import 'package:alpatrade/screens/portfolio_screen.dart';
import 'package:alpatrade/screens/activity_screen.dart';
import 'package:alpatrade/screens/strategies_screen.dart';
import 'package:alpatrade/screens/strategy_detail_screen.dart';
import 'package:alpatrade/screens/more_screen.dart';
import 'package:alpatrade/screens/news_screen.dart';
import 'package:alpatrade/screens/movers_screen.dart';
import 'package:alpatrade/screens/status_screen.dart';
import 'package:alpatrade/screens/settings_screen.dart';
import 'package:alpatrade/screens/app_scaffold.dart';
import 'package:alpatrade/widgets/auth_gate.dart';

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
      GoRoute(
        path: '/auth',
        parentNavigatorKey: _rootNavigatorKey,
        builder: (context, state) =>
            AuthScreen(returnTo: state.uri.queryParameters['from']),
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
            pageBuilder: (context, state) => const NoTransitionPage(
              child: AuthGate(
                title: 'Portfolio',
                returnTo: '/portfolio',
                child: PortfolioScreen(),
              ),
            ),
          ),
          GoRoute(
            path: '/activity',
            pageBuilder: (context, state) => const NoTransitionPage(
              child: AuthGate(
                title: 'Activity',
                returnTo: '/activity',
                child: ActivityScreen(),
              ),
            ),
          ),
          GoRoute(
            path: '/strategies',
            pageBuilder: (context, state) => const NoTransitionPage(
              child: AuthGate(
                title: 'Strategies',
                returnTo: '/strategies',
                child: StrategiesScreen(),
              ),
            ),
            routes: [
              GoRoute(
                path: 'run/:runId',
                builder: (context, state) {
                  final runId = state.pathParameters['runId']!;
                  final title = state.uri.queryParameters['title'];
                  return AuthGate(
                    title: title ?? 'Run detail',
                    returnTo: state.uri.toString(),
                    child: StrategyDetailScreen(runId: runId, title: title),
                  );
                },
              ),
            ],
          ),
          GoRoute(
            path: '/more',
            pageBuilder: (context, state) =>
                const NoTransitionPage(child: MoreScreen()),
            routes: [
              GoRoute(
                path: 'leaderboard',
                builder: (context, state) => const ResearchScreen(
                  section: 'leaderboard',
                  title: 'Leaderboard',
                ),
              ),
              GoRoute(
                path: 'leaderboard/:id',
                builder: (context, state) => ResearchStrategyScreen(
                  id: int.tryParse(state.pathParameters['id'] ?? '') ?? 0,
                ),
              ),
              GoRoute(
                path: 'my-strategies',
                builder: (context, state) => const AuthGate(
                  title: 'My strategies',
                  returnTo: '/more/my-strategies',
                  child: ResearchScreen(
                    section: 'strategies',
                    title: 'My strategies',
                  ),
                ),
              ),
              GoRoute(
                path: 'hedge-funds',
                builder: (context, state) => const AuthGate(
                  title: 'Hedge funds',
                  returnTo: '/more/hedge-funds',
                  child: ResearchScreen(section: 'funds', title: 'Hedge funds'),
                ),
              ),
              GoRoute(
                path: 'fund-performance',
                builder: (context, state) => const AuthGate(
                  title: 'Fund performance',
                  returnTo: '/more/fund-performance',
                  child: ResearchScreen(
                    section: 'performance',
                    title: 'Fund performance',
                  ),
                ),
              ),
              GoRoute(
                path: 'activists',
                builder: (context, state) => const AuthGate(
                  title: 'Activist filings',
                  returnTo: '/more/activists',
                  child: ResearchScreen(
                    section: 'activists',
                    title: 'Activist filings',
                  ),
                ),
              ),
              GoRoute(
                path: 'ipos',
                builder: (context, state) => const AuthGate(
                  title: 'IPOs',
                  returnTo: '/more/ipos',
                  child: ResearchScreen(section: 'ipos', title: 'IPOs'),
                ),
              ),
              GoRoute(
                path: 'advisor',
                builder: (context, state) => const AuthGate(
                  title: 'Daily advisor',
                  returnTo: '/more/advisor',
                  child: ResearchScreen(
                    section: 'advisor',
                    title: 'Daily advisor',
                  ),
                ),
              ),
              GoRoute(
                path: 'news',
                builder: (context, state) => const NewsScreen(),
              ),
              GoRoute(
                path: 'movers',
                builder: (context, state) => const MoversScreen(),
              ),
              GoRoute(
                path: 'status',
                builder: (context, state) => const AuthGate(
                  title: 'Agent status',
                  returnTo: '/more/status',
                  child: StatusScreen(),
                ),
              ),
              GoRoute(
                path: 'settings',
                builder: (context, state) => const SettingsScreen(),
              ),
            ],
          ),
        ],
      ),
    ],
  );
});
