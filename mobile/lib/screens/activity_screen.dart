import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/run.dart';
import 'package:alpatrade/models/trade.dart';
import 'package:alpatrade/providers/activity_provider.dart';
import 'package:alpatrade/utils/formatters.dart';
import 'package:alpatrade/widgets/empty_state.dart';
import 'package:alpatrade/widgets/error_view.dart';

class ActivityScreen extends ConsumerStatefulWidget {
  const ActivityScreen({super.key});

  @override
  ConsumerState<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends ConsumerState<ActivityScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;
  String _tradeType = 'paper';

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Activity'),
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: AppTheme.accent,
          labelColor: AppTheme.accent,
          unselectedLabelColor: AppTheme.inkDim,
          labelStyle: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
          ),
          tabs: const [
            Tab(text: 'Trades'),
            Tab(text: 'Runs'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _TradesTab(
            tradeType: _tradeType,
            onTradeTypeChanged: (t) => setState(() => _tradeType = t),
          ),
          const _RunsTab(),
        ],
      ),
    );
  }
}

class _TradesTab extends ConsumerWidget {
  final String tradeType;
  final ValueChanged<String> onTradeTypeChanged;

  const _TradesTab({required this.tradeType, required this.onTradeTypeChanged});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(tradesProvider(tradeType));

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
          child: Row(
            children: [
              _TypeChip(
                label: 'Paper',
                selected: tradeType == 'paper',
                onTap: () => onTradeTypeChanged('paper'),
              ),
              const SizedBox(width: 8),
              _TypeChip(
                label: 'Backtest',
                selected: tradeType == 'backtest',
                onTap: () => onTradeTypeChanged('backtest'),
              ),
            ],
          ),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async =>
                ref.refresh(tradesProvider(tradeType).future),
            color: AppTheme.accent,
            child: async.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => ListView(
                children: [
                  const SizedBox(height: 120),
                  ErrorView(
                    title: 'Could not load trades',
                    message: '$e',
                    onRetry: () => ref.invalidate(tradesProvider(tradeType)),
                  ),
                ],
              ),
              data: (data) {
                if (data.trades.isEmpty) {
                  return ListView(
                    children: const [
                      SizedBox(height: 120),
                      EmptyState(
                        icon: Icons.receipt_long,
                        title: 'No trades yet',
                        subtitle:
                            'No trades have been recorded for this trade type '
                            'yet. Ask the assistant to run a strategy to get '
                            'started.',
                      ),
                    ],
                  );
                }
                return ListView(
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
                  children: [
                    Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 4,
                        vertical: 8,
                      ),
                      child: Text(
                        'Trades (${data.total})',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.inkDim,
                        ),
                      ),
                    ),
                    ...data.trades.map((t) => _TradeTile(trade: t)),
                  ],
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}

class _TypeChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _TypeChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? AppTheme.accent : AppTheme.bgElev,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: selected ? AppTheme.accent : AppTheme.line),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: selected ? Colors.white : AppTheme.inkDim,
          ),
        ),
      ),
    );
  }
}

class _TradeTile extends StatelessWidget {
  final Trade trade;
  const _TradeTile({required this.trade});

  @override
  Widget build(BuildContext context) {
    final pnlColor = AppTheme.pnlColor(trade.pnl);
    final isBuy = (trade.direction ?? '').toLowerCase() == 'buy';
    final direction = (trade.direction ?? '').toUpperCase();

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
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          trade.symbol ?? '—',
                          style: const TextStyle(
                            fontFamily: AppTheme.monoFont,
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        if (direction.isNotEmpty) ...[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 6,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: isBuy
                                  ? AppTheme.accentDim
                                  : AppTheme.loss.withValues(alpha: 0.12),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Text(
                              direction,
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w600,
                                color: isBuy
                                    ? AppTheme.accentDeep
                                    : AppTheme.loss,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${Fmt.shares(trade.shares)} @ ${Fmt.usd(trade.entryPrice)}'
                      ' → ${Fmt.usd(trade.exitPrice)}',
                      style: TextStyle(
                        fontSize: 12,
                        color: AppTheme.inkDim,
                        fontFamily: AppTheme.monoFont,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${Fmt.dateTimeShort(trade.entryTime)}'
                      '${trade.exitTime != null && trade.exitTime!.isNotEmpty ? ' → ${Fmt.dateTimeShort(trade.exitTime)}' : ''}',
                      style: TextStyle(
                        fontSize: 11,
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
                    Fmt.signedUsd(trade.pnl),
                    style: TextStyle(
                      fontFamily: AppTheme.monoFont,
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: pnlColor,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    Fmt.pct(trade.pnlPct, signed: true),
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
          if (trade.reason != null && trade.reason!.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              trade.reason!,
              style: TextStyle(
                fontSize: 11,
                color: AppTheme.inkDim,
                height: 1.4,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _RunsTab extends ConsumerWidget {
  const _RunsTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(runsProvider);

    return RefreshIndicator(
      onRefresh: () async => ref.refresh(runsProvider.future),
      color: AppTheme.accent,
      child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(
          children: [
            const SizedBox(height: 120),
            ErrorView(
              title: 'Could not load runs',
              message: '$e',
              onRetry: () => ref.invalidate(runsProvider),
            ),
          ],
        ),
        data: (data) {
          if (data.runs.isEmpty) {
            return ListView(
              children: const [
                SizedBox(height: 120),
                EmptyState(
                  icon: Icons.timeline,
                  title: 'No runs yet',
                  subtitle:
                      'No strategy runs have been recorded yet. Ask the '
                      'assistant to run a strategy to get started.',
                ),
              ],
            );
          }
          return ListView(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
                child: Text(
                  'Runs (${data.total})',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.inkDim,
                  ),
                ),
              ),
              ...data.runs.map((r) => _RunTile(run: r)),
            ],
          );
        },
      ),
    );
  }
}

class _RunTile extends StatelessWidget {
  final Run run;
  const _RunTile({required this.run});

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'completed':
        return AppTheme.gain;
      case 'running':
        return AppTheme.accent;
      case 'failed':
      case 'error':
        return AppTheme.loss;
      default:
        return AppTheme.inkDim;
    }
  }

  @override
  Widget build(BuildContext context) {
    final statusColor = _statusColor(run.status);

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
              Expanded(
                child: Text(
                  Fmt.titleize(run.strategySlug ?? run.strategy),
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              _Chip(
                label: run.mode,
                color: AppTheme.accentDeep,
                bg: AppTheme.accentDim,
              ),
              const SizedBox(width: 6),
              _Chip(
                label: run.status,
                color: statusColor,
                bg: statusColor.withValues(alpha: 0.12),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Started ${Fmt.dateTimeShort(run.startedAt)}'
            '${run.completedAt != null && run.completedAt!.isNotEmpty ? '  ·  done ${Fmt.dateTimeShort(run.completedAt)}' : ''}',
            style: TextStyle(
              fontSize: 11,
              color: AppTheme.inkDim,
              fontFamily: AppTheme.monoFont,
            ),
          ),
        ],
      ),
    );
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
        label.toUpperCase(),
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}
