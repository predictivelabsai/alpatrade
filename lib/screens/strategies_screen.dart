import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/strategy.dart';
import 'package:alpatrade/providers/strategies_provider.dart';
import 'package:alpatrade/utils/formatters.dart';
import 'package:alpatrade/widgets/empty_state.dart';
import 'package:alpatrade/widgets/error_view.dart';

class StrategiesScreen extends ConsumerStatefulWidget {
  const StrategiesScreen({super.key});

  @override
  ConsumerState<StrategiesScreen> createState() => _StrategiesScreenState();
}

class _StrategiesScreenState extends ConsumerState<StrategiesScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 2, vsync: this);

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Strategies'),
        bottom: TabBar(
          controller: _tabs,
          labelColor: AppTheme.accent,
          unselectedLabelColor: AppTheme.inkDim,
          indicatorColor: AppTheme.accent,
          tabs: const [
            Tab(text: 'Top'),
            Tab(text: 'Reports'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabs,
        children: const [_TopTab(), _ReportsTab()],
      ),
    );
  }
}

class _TopTab extends ConsumerWidget {
  const _TopTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(topStrategiesProvider);
    return RefreshIndicator(
      onRefresh: () async => ref.refresh(topStrategiesProvider.future),
      color: AppTheme.accent,
      child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(
          children: [
            const SizedBox(height: 120),
            ErrorView(
              title: 'Could not load rankings',
              message: '$e',
              onRetry: () => ref.invalidate(topStrategiesProvider),
            ),
          ],
        ),
        data: (items) {
          if (items.isEmpty) {
            return ListView(
              children: const [
                SizedBox(height: 120),
                EmptyState(
                  icon: Icons.leaderboard_outlined,
                  title: 'No strategies ranked yet',
                  subtitle:
                      'Once backtests have run, the top performing strategies '
                      'will appear here.',
                ),
              ],
            );
          }
          return ListView.builder(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
            itemCount: items.length,
            itemBuilder: (_, i) =>
                _TopStrategyTile(rank: i + 1, strategy: items[i]),
          );
        },
      ),
    );
  }
}

class _TopStrategyTile extends StatelessWidget {
  final int rank;
  final TopStrategy strategy;
  const _TopStrategyTile({required this.rank, required this.strategy});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 26,
                height: 26,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppTheme.accentDim,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '$rank',
                  style: TextStyle(
                    fontFamily: AppTheme.monoFont,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.accentDeep,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  Fmt.titleize(strategy.strategySlug),
                  style: const TextStyle(
                    fontFamily: AppTheme.monoFont,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _StatChip(
                label: 'Sharpe',
                value: Fmt.number(strategy.avgSharpe, decimals: 1),
              ),
              _StatChip(
                label: 'Return',
                value: Fmt.pct(strategy.avgReturn, signed: true),
                valueColor: AppTheme.pnlColor(strategy.avgReturn),
              ),
              _StatChip(label: 'Win%', value: Fmt.pct(strategy.avgWinRate)),
              _StatChip(label: 'Trades', value: '${strategy.totalTrades}'),
            ],
          ),
        ],
      ),
    );
  }
}

class _StatChip extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;
  const _StatChip({required this.label, required this.value, this.valueColor});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: AppTheme.bgRaise,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label, style: TextStyle(fontSize: 11, color: AppTheme.inkDim)),
          const SizedBox(width: 6),
          Text(
            value,
            style: TextStyle(
              fontFamily: AppTheme.monoFont,
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: valueColor ?? AppTheme.ink,
            ),
          ),
        ],
      ),
    );
  }
}

class _ReportsTab extends ConsumerWidget {
  const _ReportsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(reportsProvider);
    return RefreshIndicator(
      onRefresh: () async => ref.refresh(reportsProvider.future),
      color: AppTheme.accent,
      child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(
          children: [
            const SizedBox(height: 120),
            ErrorView(
              title: 'Could not load reports',
              message: '$e',
              onRetry: () => ref.invalidate(reportsProvider),
            ),
          ],
        ),
        data: (items) {
          if (items.isEmpty) {
            return ListView(
              children: const [
                SizedBox(height: 120),
                EmptyState(
                  icon: Icons.assessment_outlined,
                  title: 'No reports yet',
                  subtitle: 'Completed backtest runs will be listed here.',
                ),
              ],
            );
          }
          return ListView.builder(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
            itemCount: items.length,
            itemBuilder: (_, i) => _ReportTile(report: items[i]),
          );
        },
      ),
    );
  }
}

class _ReportTile extends StatelessWidget {
  final ReportSummary report;
  const _ReportTile({required this.report});

  @override
  Widget build(BuildContext context) {
    final pnlColor = AppTheme.pnlColor(report.totalPnl);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () {
            final runId = Uri.encodeComponent(report.runId);
            final title = Uri.encodeQueryComponent(
              Fmt.titleize(report.strategySlug ?? report.strategy),
            );
            context.push('/strategies/run/$runId?title=$title');
          },
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        Fmt.titleize(report.strategySlug ?? report.strategy),
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    if (report.mode != null && report.mode!.isNotEmpty)
                      _Chip(
                        label: report.mode!.toUpperCase(),
                        color: AppTheme.accentDeep,
                        bg: AppTheme.accentDim,
                      ),
                    const SizedBox(width: 6),
                    _Chip(
                      label: Fmt.titleize(report.status),
                      color: _statusColor(report.status),
                      bg: _statusColor(report.status).withValues(alpha: 0.12),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Text(
                      Fmt.signedUsd(report.totalPnl),
                      style: TextStyle(
                        fontFamily: AppTheme.monoFont,
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: pnlColor,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '(${Fmt.pct(report.totalReturn, signed: true)})',
                      style: TextStyle(
                        fontFamily: AppTheme.monoFont,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: pnlColor,
                      ),
                    ),
                    const Spacer(),
                    Text(
                      Fmt.dateShort(report.runDate),
                      style: TextStyle(fontSize: 12, color: AppTheme.inkDim),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

Color _statusColor(String status) {
  switch (status.toLowerCase()) {
    case 'completed':
      return AppTheme.gain;
    case 'running':
    case 'in_progress':
      return AppTheme.accent;
    case 'failed':
    case 'error':
      return AppTheme.loss;
    default:
      return AppTheme.inkDim;
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final Color color;
  final Color bg;
  const _Chip({required this.label, required this.color, required this.bg});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}
