import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/api_config.dart';
import 'package:alpatrade/config/constants.dart';
import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/providers/locale_provider.dart';

/// Human-readable names for the supported locale codes.
const Map<String, String> _localeNames = {
  'en': 'English',
  'et': 'Eesti',
  'de': 'Deutsch',
  'fr': 'Français',
  'sv': 'Svenska',
  'lv': 'Latviešu',
  'no': 'Norsk',
  'da': 'Dansk',
  'pl': 'Polski',
  'nl': 'Nederlands',
  'fi': 'Suomi',
  'lt': 'Lietuvių',
};

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final locale = ref.watch(localeProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(12, 16, 12, 24),
        children: [
          const _SectionLabel('Language'),
          _Card(
            child: Column(
              children: [
                for (
                  var i = 0;
                  i < AppConstants.supportedLocales.length;
                  i++
                ) ...[
                  if (i > 0)
                    Divider(
                      height: 1,
                      thickness: 1,
                      color: AppTheme.line,
                      indent: 16,
                    ),
                  _LocaleTile(
                    code: AppConstants.supportedLocales[i],
                    selected: AppConstants.supportedLocales[i] == locale,
                    onTap: () => ref
                        .read(localeProvider.notifier)
                        .set(AppConstants.supportedLocales[i]),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 24),
          const _SectionLabel('About'),
          _Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'AlpaTrade',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.ink,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'AI trading assistant for markets, news and paper trades.',
                    style: TextStyle(
                      fontSize: 13,
                      color: AppTheme.inkMuted,
                      height: 1.4,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 8,
                    ),
                    decoration: BoxDecoration(
                      color: AppTheme.accentDim,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      'Paper trading — simulated, not investment advice.',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.accentDeep,
                        height: 1.4,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
          const _SectionLabel('API'),
          const _Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _ApiRow(label: 'Base URL', value: ApiConfig.baseUrl),
                  SizedBox(height: 12),
                  _ApiRow(label: 'Voice WS', value: ApiConfig.voiceWsUrl),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 8),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w600,
          color: AppTheme.inkDim,
        ),
      ),
    );
  }
}

class _Card extends StatelessWidget {
  final Widget child;
  const _Card({required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: child,
    );
  }
}

class _LocaleTile extends StatelessWidget {
  final String code;
  final bool selected;
  final VoidCallback onTap;

  const _LocaleTile({
    required this.code,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap,
      title: Text(
        _localeNames[code] ?? code,
        style: TextStyle(
          fontSize: 15,
          fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
          color: AppTheme.ink,
        ),
      ),
      subtitle: Text(
        code.toUpperCase(),
        style: TextStyle(
          fontSize: 11,
          fontFamily: AppTheme.monoFont,
          color: AppTheme.inkDim,
        ),
      ),
      trailing: selected
          ? Icon(Icons.check, color: AppTheme.accent, size: 22)
          : null,
    );
  }
}

class _ApiRow extends StatelessWidget {
  final String label;
  final String value;
  const _ApiRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(fontSize: 12, color: AppTheme.inkDim)),
        const SizedBox(height: 4),
        SelectableText(
          value,
          style: TextStyle(
            fontSize: 13,
            fontFamily: AppTheme.monoFont,
            color: AppTheme.ink,
          ),
        ),
      ],
    );
  }
}
