import 'package:flutter/material.dart';
import 'package:alpatrade/config/theme.dart';

class OrderPreset {
  final String side; // 'buy' | 'sell'
  final String orderType; // 'market' | 'limit'
  const OrderPreset(this.side, this.orderType);
}

class _Card {
  final IconData icon;
  final String label;
  final OrderPreset preset;
  const _Card(this.icon, this.label, this.preset);
}

/// Horizontal strip of one-tap order presets shown just above the chat input.
/// Tapping opens the order ticket (POST /v2/order) pre-set to that side/type.
class QuickOrderBar extends StatelessWidget {
  final ValueChanged<OrderPreset> onSelect;

  const QuickOrderBar({super.key, required this.onSelect});

  static const _cards = [
    _Card(Icons.trending_up, 'Buy limit', OrderPreset('buy', 'limit')),
    _Card(Icons.trending_down, 'Sell limit', OrderPreset('sell', 'limit')),
    _Card(Icons.bolt, 'Buy market', OrderPreset('buy', 'market')),
    _Card(Icons.bolt_outlined, 'Sell market', OrderPreset('sell', 'market')),
  ];

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
        itemCount: _cards.length,
        separatorBuilder: (_, _) => const SizedBox(width: 6),
        itemBuilder: (context, i) {
          final c = _cards[i];
          final buy = c.preset.side == 'buy';
          return _OrderCard(
            icon: c.icon,
            label: c.label,
            accent: buy ? AppTheme.gain : AppTheme.loss,
            onTap: () => onSelect(c.preset),
          );
        },
      ),
    );
  }
}

class _OrderCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color accent;
  final VoidCallback onTap;

  const _OrderCard({
    required this.icon,
    required this.label,
    required this.accent,
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
              Icon(icon, size: 15, color: accent),
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
