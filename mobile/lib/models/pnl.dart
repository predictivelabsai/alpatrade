/// Per-symbol P&L breakdown row from GET /v2/pnl/{run_id}.
class PnlSymbol {
  final String symbol;
  final double totalPnl;
  final double totalFees;
  final int tradeCount;
  final int winCount;
  final int lossCount;
  final double? avgPnl;

  const PnlSymbol({
    required this.symbol,
    required this.totalPnl,
    required this.totalFees,
    required this.tradeCount,
    required this.winCount,
    required this.lossCount,
    this.avgPnl,
  });

  factory PnlSymbol.fromJson(Map<String, dynamic> j) => PnlSymbol(
    symbol: j['symbol'] as String? ?? '',
    totalPnl: (j['total_pnl'] as num?)?.toDouble() ?? 0,
    totalFees: (j['total_fees'] as num?)?.toDouble() ?? 0,
    tradeCount: (j['trade_count'] as num?)?.toInt() ?? 0,
    winCount: (j['win_count'] as num?)?.toInt() ?? 0,
    lossCount: (j['loss_count'] as num?)?.toInt() ?? 0,
    avgPnl: (j['avg_pnl'] as num?)?.toDouble(),
  );
}

/// One day of realized P&L from GET /v2/pnl/{run_id}.
class DailyPnl {
  final String date;
  final double pnl;
  final int tradeCount;

  const DailyPnl({
    required this.date,
    required this.pnl,
    required this.tradeCount,
  });

  factory DailyPnl.fromJson(Map<String, dynamic> j) => DailyPnl(
    date: j['date'] as String? ?? '',
    pnl: (j['pnl'] as num?)?.toDouble() ?? 0,
    tradeCount: (j['trade_count'] as num?)?.toInt() ?? 0,
  );
}

/// GET /v2/pnl/{run_id} — realized P&L breakdown for a single run.
class PnlBreakdown {
  final String runId;
  final String? strategy;
  final String? mode;
  final double totalPnl;
  final double? totalReturn;
  final double totalFees;
  final double? winRate;
  final int winningTrades;
  final int losingTrades;
  final int totalTrades;
  final double? sharpeRatio;
  final List<PnlSymbol> perSymbol;
  final List<DailyPnl> dailyPnl;

  const PnlBreakdown({
    required this.runId,
    this.strategy,
    this.mode,
    required this.totalPnl,
    this.totalReturn,
    required this.totalFees,
    this.winRate,
    required this.winningTrades,
    required this.losingTrades,
    required this.totalTrades,
    this.sharpeRatio,
    required this.perSymbol,
    required this.dailyPnl,
  });

  factory PnlBreakdown.fromJson(Map<String, dynamic> j) => PnlBreakdown(
    runId: j['run_id']?.toString() ?? '',
    strategy: j['strategy'] as String?,
    mode: j['mode'] as String?,
    totalPnl: (j['total_pnl'] as num?)?.toDouble() ?? 0,
    totalReturn: (j['total_return'] as num?)?.toDouble(),
    totalFees: (j['total_fees'] as num?)?.toDouble() ?? 0,
    winRate: (j['win_rate'] as num?)?.toDouble(),
    winningTrades: (j['winning_trades'] as num?)?.toInt() ?? 0,
    losingTrades: (j['losing_trades'] as num?)?.toInt() ?? 0,
    totalTrades: (j['total_trades'] as num?)?.toInt() ?? 0,
    sharpeRatio: (j['sharpe_ratio'] as num?)?.toDouble(),
    perSymbol: ((j['per_symbol'] as List?) ?? [])
        .map((e) => PnlSymbol.fromJson(e as Map<String, dynamic>))
        .toList(),
    dailyPnl: ((j['daily_pnl'] as List?) ?? [])
        .map((e) => DailyPnl.fromJson(e as Map<String, dynamic>))
        .toList(),
  );
}
