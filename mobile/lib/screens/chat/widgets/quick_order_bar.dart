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
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 480) {
          return SizedBox(
            height: 40,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
              child: Row(
                children: [
                  for (var i = 0; i < _cards.length; i++) ...[
                    if (i > 0) const SizedBox(width: 5),
                    Expanded(child: _buildCard(_cards[i], compact: true)),
                  ],
                ],
              ),
            ),
          );
        }
        return SizedBox(
          height: 40,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
            itemCount: _cards.length,
            separatorBuilder: (_, _) => const SizedBox(width: 6),
            itemBuilder: (context, i) => _buildCard(_cards[i]),
          ),
        );
      },
    );
  }

  Widget _buildCard(_Card card, {bool compact = false}) {
    final buy = card.preset.side == 'buy';
    return _OrderCard(
      icon: card.icon,
      label: card.label,
      accent: buy ? AppTheme.gain : AppTheme.loss,
      compact: compact,
      onTap: () => onSelect(card.preset),
    );
  }
}

class _OrderCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color accent;
  final bool compact;
  final VoidCallback onTap;

  const _OrderCard({
    required this.icon,
    required this.label,
    required this.accent,
    this.compact = false,
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
          alignment: Alignment.center,
          padding: EdgeInsets.symmetric(
            horizontal: compact ? 4 : 12,
            vertical: 8,
          ),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: AppTheme.line),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            mainAxisSize: compact ? MainAxisSize.max : MainAxisSize.min,
            children: [
              if (!compact) ...[
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
              ] else
                Expanded(
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(
                      label,
                      maxLines: 1,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.ink,
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
