import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/screens/news_screen.dart';
import 'package:alpatrade/screens/movers_screen.dart';
import 'package:alpatrade/screens/status_screen.dart';
import 'package:alpatrade/screens/settings_screen.dart';

class MoreScreen extends ConsumerWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(12, 16, 12, 24),
        children: [
          Container(
            decoration: BoxDecoration(
              color: AppTheme.bgElev,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppTheme.line),
            ),
            child: Column(
              children: [
                _MoreTile(
                  icon: Icons.article_outlined,
                  title: 'Market news',
                  subtitle: 'Latest headlines by symbol',
                  onTap: () => _push(context, const NewsScreen()),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.trending_up,
                  title: 'Market movers',
                  subtitle: "Today's biggest gainers and losers",
                  onTap: () => _push(context, const MoversScreen()),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.dns_outlined,
                  title: 'Agent status',
                  subtitle: 'Live trading agent run state',
                  onTap: () => _push(context, const StatusScreen()),
                ),
                const _TileDivider(),
                _MoreTile(
                  icon: Icons.settings_outlined,
                  title: 'Settings',
                  subtitle: 'Language, about and API',
                  onTap: () => _push(context, const SettingsScreen()),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  void _push(BuildContext context, Widget screen) {
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
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
