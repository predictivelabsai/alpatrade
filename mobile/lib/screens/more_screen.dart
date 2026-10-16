import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:alpatrade/config/theme.dart';

class MoreScreen extends ConsumerWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(12, 16, 12, 24),
        children: [
          Material(
            color: AppTheme.bgElev,
            clipBehavior: Clip.antiAlias,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
              side: BorderSide(color: AppTheme.line),
            ),
            child: Column(
              children: [
                _MoreTile(
                  icon: Icons.emoji_events_outlined,
                  title: 'Leaderboard',
                  subtitle: 'Live and backtested strategies',
                  onTap: () => context.push('/more/leaderboard'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.bookmarks_outlined,
                  title: 'My strategies',
                  subtitle: 'Your private strategy library',
                  onTap: () => context.push('/more/my-strategies'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.account_balance_outlined,
                  title: 'Hedge funds',
                  subtitle: 'Search institutional 13F portfolios',
                  onTap: () => context.push('/more/hedge-funds'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.insights_outlined,
                  title: 'Fund performance',
                  subtitle: '13F estimates compared with SPY',
                  onTap: () => context.push('/more/fund-performance'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.description_outlined,
                  title: 'Activist filings',
                  subtitle: 'Recent institutional disclosures',
                  onTap: () => context.push('/more/activists'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.rocket_launch_outlined,
                  title: 'IPOs',
                  subtitle: 'New listings and upcoming offerings',
                  onTap: () => context.push('/more/ipos'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.lightbulb_outline,
                  title: 'Daily advisor',
                  subtitle: 'Your latest paper-account reviews',
                  onTap: () => context.push('/more/advisor'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.article_outlined,
                  title: 'Market news',
                  subtitle: 'Latest headlines by symbol',
                  onTap: () => context.push('/more/news'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.trending_up,
                  title: 'Market movers',
                  subtitle: "Today's biggest gainers and losers",
                  onTap: () => context.push('/more/movers'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.dns_outlined,
                  title: 'Agent status',
                  subtitle: 'Live trading agent run state',
                  onTap: () => context.push('/more/status'),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.settings_outlined,
                  title: 'Settings',
                  subtitle: 'Language, about and API',
                  onTap: () => context.push('/more/settings'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _MoreTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _MoreTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap,
      leading: Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(
          color: AppTheme.accentDim,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Icon(icon, color: AppTheme.accentDeep, size: 22),
      ),
      title: Text(
        title,
        style: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: AppTheme.ink,
        ),
      ),
      subtitle: Text(
        subtitle,
        style: TextStyle(fontSize: 12, color: AppTheme.inkDim),
      ),
      trailing: Icon(Icons.chevron_right, color: AppTheme.inkDim, size: 22),
    );
  }
}

class _TileDivider extends StatelessWidget {
  const _TileDivider();

  @override
  Widget build(BuildContext context) {
    return Divider(height: 1, thickness: 1, color: AppTheme.line, indent: 68);
  }
}
