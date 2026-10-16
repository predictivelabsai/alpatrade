import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/position.dart';
import 'package:alpatrade/providers/positions_provider.dart';
import 'package:alpatrade/utils/formatters.dart';
import 'package:alpatrade/widgets/empty_state.dart';
import 'package:alpatrade/widgets/error_view.dart';

class PortfolioScreen extends ConsumerWidget {
  const PortfolioScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(positionsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Portfolio')),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(positionsProvider.future),
        color: AppTheme.accent,
        child: async.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(
            children: [
              const SizedBox(height: 120),
              ErrorView(
                title: 'Could not load positions',
                message: '$e',
                onRetry: () => ref.invalidate(positionsProvider),
              ),
            ],
          ),
          data: (data) {
            if (data.positions.isEmpty) {
              return ListView(
                children: const [
                  SizedBox(height: 120),
                  EmptyState(
                    icon: Icons.pie_chart_outline,
                    title: 'No open positions',
                    subtitle:
                        'Your paper account has no open positions yet. Ask the '
                        'assistant to place a paper trade to get started.',
                  ),
                ],
              );
            }
            return ListView(
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
              children: [
                _AccountSummary(data: data),
                const SizedBox(height: 16),
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 4,
                    vertical: 8,
                  ),
                  child: Text(
                    'Open positions (${data.total})',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.inkDim,
                    ),
                  ),
                ),
                ...data.positions.map((p) => _PositionTile(position: p)),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _AccountSummary extends StatelessWidget {
  final PositionsResponse data;
  const _AccountSummary({required this.data});

  @override
  Widget build(BuildContext context) {
    final pnl = data.totalUnrealizedPnl;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppTheme.accent,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Market value',
            style: TextStyle(
              fontSize: 12,
              color: Colors.white.withValues(alpha: 0.8),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            Fmt.usd(data.totalMarketValue),
            style: const TextStyle(
              fontFamily: AppTheme.monoFont,
              fontSize: 30,
              fontWeight: FontWeight.w700,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Icon(
                pnl >= 0 ? Icons.trending_up : Icons.trending_down,
                size: 16,
                color: Colors.white,
              ),
              const SizedBox(width: 6),
              Text(
                '${Fmt.signedUsd(pnl)}  (${Fmt.pct(data.totalUnrealizedPnlPct, signed: true)})',
                style: const TextStyle(
                  fontFamily: AppTheme.monoFont,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: Colors.white,
                ),
              ),
              const SizedBox(width: 6),
              Text(
                'unrealized',
                style: TextStyle(
                  fontSize: 12,
                  color: Colors.white.withValues(alpha: 0.8),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PositionTile extends StatelessWidget {
  final Position position;
  const _PositionTile({required this.position});

  @override
  Widget build(BuildContext context) {
    final pnlColor = AppTheme.pnlColor(position.unrealizedPnl);
    final isShort = position.side.toLowerCase() == 'short';

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      position.symbol,
                      style: const TextStyle(
                        fontFamily: AppTheme.monoFont,
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 6,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: isShort
                            ? AppTheme.loss.withValues(alpha: 0.12)
                            : AppTheme.accentDim,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        position.side.toUpperCase(),
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          color: isShort ? AppTheme.loss : AppTheme.accentDeep,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  '${Fmt.shares(position.shares)} @ ${Fmt.usd(position.avgEntryPrice)}'
                  '  ·  now ${Fmt.usd(position.currentPrice)}',
                  style: TextStyle(
                    fontSize: 12,
                    color: AppTheme.inkDim,
                    fontFamily: AppTheme.monoFont,
                  ),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                Fmt.usd(position.marketValue),
                style: const TextStyle(
                  fontFamily: AppTheme.monoFont,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '${Fmt.signedUsd(position.unrealizedPnl)} (${Fmt.pct(position.unrealizedPnlPct, signed: true)})',
                style: TextStyle(
                  fontFamily: AppTheme.monoFont,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: pnlColor,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
