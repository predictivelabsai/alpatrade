import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/pnl.dart';
import 'package:alpatrade/providers/strategies_provider.dart';
import 'package:alpatrade/utils/formatters.dart';
import 'package:alpatrade/widgets/empty_state.dart';
import 'package:alpatrade/widgets/error_view.dart';

class StrategyDetailScreen extends ConsumerWidget {
  final String runId;
  final String? title;
  const StrategyDetailScreen({super.key, required this.runId, this.title});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(pnlProvider(runId));
    return Scaffold(
      appBar: AppBar(title: Text(title ?? 'Run detail')),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorView(
          title: 'Could not load P&L',
          message: '$e',
          onRetry: () => ref.invalidate(pnlProvider(runId)),
        ),
        data: (pnl) => ListView(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
          children: [
            _PnlSummary(pnl: pnl),
            const SizedBox(height: 16),
            _StatGrid(pnl: pnl),
            const SizedBox(height: 16),
            const _SectionLabel('Cumulative P&L'),
            const SizedBox(height: 8),
            _PnlChartCard(daily: pnl.dailyPnl),
            const SizedBox(height: 16),
            if (pnl.perSymbol.isNotEmpty) ...[
              _SectionLabel('By symbol (${pnl.perSymbol.length})'),
              const SizedBox(height: 8),
              ...pnl.perSymbol.map((s) => _SymbolTile(symbol: s)),
            ],
          ],
        ),
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
      padding: const EdgeInsets.symmetric(horizontal: 4),
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

class _PnlSummary extends StatelessWidget {
  final PnlBreakdown pnl;
  const _PnlSummary({required this.pnl});

  @override
  Widget build(BuildContext context) {
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
            'Total P&L',
            style: TextStyle(
              fontSize: 12,
              color: Colors.white.withValues(alpha: 0.8),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            Fmt.signedUsd(pnl.totalPnl),
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
                pnl.totalPnl >= 0 ? Icons.trending_up : Icons.trending_down,
                size: 16,
                color: Colors.white,
              ),
              const SizedBox(width: 6),
              Text(
                Fmt.pct(pnl.totalReturn, signed: true),
                style: const TextStyle(
                  fontFamily: AppTheme.monoFont,
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: Colors.white,
                ),
              ),
              const SizedBox(width: 6),
              Text(
                'return',
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

class _StatGrid extends StatelessWidget {
  final PnlBreakdown pnl;
  const _StatGrid({required this.pnl});

  @override
  Widget build(BuildContext context) {
    final stats = <(String, String, Color?)>[
      ('Win rate', Fmt.pct(pnl.winRate), null),
      ('Sharpe', Fmt.number(pnl.sharpeRatio, decimals: 2), null),
      ('Trades', '${pnl.totalTrades}', null),
      ('Winning', '${pnl.winningTrades}', AppTheme.gain),
      ('Losing', '${pnl.losingTrades}', AppTheme.loss),
      ('Fees', Fmt.usd(pnl.totalFees), null),
    ];
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: Wrap(
        spacing: 12,
        runSpacing: 14,
        children: [
          for (final s in stats)
            SizedBox(
              width: (MediaQuery.of(context).size.width - 24 - 28 - 24) / 3,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    s.$1,
                    style: TextStyle(fontSize: 11, color: AppTheme.inkDim),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    s.$2,
                    style: TextStyle(
                      fontFamily: AppTheme.monoFont,
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: s.$3 ?? AppTheme.ink,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _PnlChartCard extends StatelessWidget {
  final List<DailyPnl> daily;
  const _PnlChartCard({required this.daily});

  @override
  Widget build(BuildContext context) {
    if (daily.isEmpty) {
      return Container(
        padding: const EdgeInsets.symmetric(vertical: 24),
        decoration: BoxDecoration(
          color: AppTheme.bgElev,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppTheme.line),
        ),
        child: const EmptyState(
          icon: Icons.show_chart,
          title: 'No daily P&L',
          subtitle: 'This run has no per-day P&L data to chart.',
        ),
      );
    }

    final sorted = [...daily]..sort((a, b) => a.date.compareTo(b.date));
    final spots = <FlSpot>[];
    var running = 0.0;
    for (var i = 0; i < sorted.length; i++) {
      running += sorted[i].pnl;
      spots.add(FlSpot(i.toDouble(), running));
    }

    var minY = spots.first.y, maxY = spots.first.y;
    for (final s in spots) {
      if (s.y < minY) minY = s.y;
      if (s.y > maxY) maxY = s.y;
    }
    final pad = ((maxY - minY).abs() * 0.1).clamp(1.0, double.infinity);
    minY -= pad;
    maxY += pad;

    return Container(
      padding: const EdgeInsets.fromLTRB(8, 16, 16, 8),
      height: 220,
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: LineChart(
        LineChartData(
          minY: minY,
          maxY: maxY,
          minX: 0,
          maxX: (spots.length - 1).toDouble(),
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            horizontalInterval: ((maxY - minY) / 4).clamp(1.0, double.infinity),
            getDrawingHorizontalLine: (_) =>
                FlLine(color: AppTheme.line, strokeWidth: 1),
          ),
          titlesData: FlTitlesData(
            topTitles: const AxisTitles(
              sideTitles: SideTitles(showTitles: false),
            ),
            rightTitles: const AxisTitles(
              sideTitles: SideTitles(showTitles: false),
            ),
            bottomTitles: const AxisTitles(
              sideTitles: SideTitles(showTitles: false),
            ),
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 44,
                getTitlesWidget: (value, meta) => Text(
                  Fmt.usd(value, decimals: 0),
                  style: TextStyle(fontSize: 9, color: AppTheme.inkDim),
                ),
              ),
            ),
          ),
          borderData: FlBorderData(show: false),
          lineTouchData: const LineTouchData(enabled: false),
          lineBarsData: [
            LineChartBarData(
              spots: spots,
              isCurved: true,
              color: AppTheme.accent,
              barWidth: 2,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: true,
                color: AppTheme.accentDim.withValues(alpha: 0.5),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SymbolTile extends StatelessWidget {
  final PnlSymbol symbol;
  const _SymbolTile({required this.symbol});

  @override
  Widget build(BuildContext context) {
    final pnlColor = AppTheme.pnlColor(symbol.totalPnl);
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
                Text(
                  symbol.symbol,
                  style: const TextStyle(
                    fontFamily: AppTheme.monoFont,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  '${symbol.tradeCount} trades  ·  ${symbol.winCount}W / ${symbol.lossCount}L',
                  style: TextStyle(
                    fontSize: 12,
                    color: AppTheme.inkDim,
                    fontFamily: AppTheme.monoFont,
                  ),
                ),
              ],
            ),
          ),
          Text(
            Fmt.signedUsd(symbol.totalPnl),
            style: TextStyle(
              fontFamily: AppTheme.monoFont,
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: pnlColor,
            ),
          ),
        ],
      ),
    );
  }
}
