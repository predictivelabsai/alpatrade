import 'package:flutter/material.dart';
import 'package:alpatrade/config/theme.dart';

class _OrderTemplate {
  final IconData icon;
  final String label;
  final String template; // editable prompt inserted into the input
  const _OrderTemplate(this.icon, this.label, this.template);
}

/// Horizontal strip of one-tap order templates shown just above the chat input.
/// Tapping prefills the text field with an editable order so the user can tweak
/// symbol/qty/price, then send (the agent previews & asks to confirm — paper only).
class QuickOrderBar extends StatelessWidget {
  final ValueChanged<String> onTemplate;

  const QuickOrderBar({super.key, required this.onTemplate});

  static const _templates = [
    _OrderTemplate(
      Icons.trending_up,
      'Buy limit',
      'Buy 10 shares of AAPL with a limit price of \$150',
    ),
    _OrderTemplate(
      Icons.trending_down,
      'Sell limit',
      'Sell 10 shares of AAPL with a limit price of \$200',
    ),
    _OrderTemplate(
      Icons.shield_outlined,
      'Stop loss',
      'Set a stop-loss on my AAPL position at \$140',
    ),
    _OrderTemplate(
      Icons.call_split,
      'Bracket',
      'Buy 10 AAPL at limit \$150 with take-profit \$170 and stop-loss \$140',
    ),
    _OrderTemplate(
      Icons.close_fullscreen,
      'Close position',
      'Close my entire AAPL position at market',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
        itemCount: _templates.length,
        separatorBuilder: (_, _) => const SizedBox(width: 6),
        itemBuilder: (context, i) {
          final t = _templates[i];
          return _OrderCard(
            icon: t.icon,
            label: t.label,
            onTap: () => onTemplate(t.template),
          );
        },
      ),
    );
  }
}

class _OrderCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _OrderCard({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppTheme.bgElev,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: AppTheme.line),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 15, color: AppTheme.accent),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.ink,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
