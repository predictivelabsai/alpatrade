/// Aggregated ranking row from GET /v2/top.
class TopStrategy {
  final String strategySlug;
  final double? avgSharpe;
  final double? avgReturn;
  final double? avgAnnReturn;
  final double? avgWinRate;
  final double? avgDrawdown;
  final int totalTrades;
  final int totalRuns;
  final double? avgPnl;

  const TopStrategy({
    required this.strategySlug,
    this.avgSharpe,
    this.avgReturn,
    this.avgAnnReturn,
    this.avgWinRate,
    this.avgDrawdown,
    required this.totalTrades,
    required this.totalRuns,
    this.avgPnl,
  });

  factory TopStrategy.fromJson(Map<String, dynamic> j) => TopStrategy(
    strategySlug: j['strategy_slug'] as String? ?? '',
    avgSharpe: (j['avg_sharpe'] as num?)?.toDouble(),
    avgReturn: (j['avg_return'] as num?)?.toDouble(),
    avgAnnReturn: (j['avg_ann_return'] as num?)?.toDouble(),
    avgWinRate: (j['avg_win_rate'] as num?)?.toDouble(),
    avgDrawdown: (j['avg_drawdown'] as num?)?.toDouble(),
    totalTrades: (j['total_trades'] as num?)?.toInt() ?? 0,
    totalRuns: (j['total_runs'] as num?)?.toInt() ?? 0,
    avgPnl: (j['avg_pnl'] as num?)?.toDouble(),
  );

  /// Parses the raw GET /v2/top payload (a JSON array).
  static List<TopStrategy> listFromJson(List<dynamic> raw) =>
      raw.map((e) => TopStrategy.fromJson(e as Map<String, dynamic>)).toList();
}

/// One backtest/run summary row from GET /v2/report.
class ReportSummary {
  final String runId;
  final String? mode;
  final String? strategy;
  final String? strategySlug;
  final String status;
  final double? initialCapital;
  final double? totalPnl;
  final double? totalReturn;
  final double? annualizedReturn;
  final double? sharpeRatio;
  final int? totalTrades;
  final String? dataStart;
  final String? dataEnd;
  final String? runDate;

  const ReportSummary({
    required this.runId,
    this.mode,
    this.strategy,
    this.strategySlug,
    required this.status,
    this.initialCapital,
    this.totalPnl,
    this.totalReturn,
    this.annualizedReturn,
    this.sharpeRatio,
    this.totalTrades,
    this.dataStart,
    this.dataEnd,
    this.runDate,
  });

  factory ReportSummary.fromJson(Map<String, dynamic> j) => ReportSummary(
    runId: j['run_id']?.toString() ?? '',
    mode: j['mode'] as String?,
    strategy: j['strategy'] as String?,
    strategySlug: j['strategy_slug'] as String?,
    status: j['status'] as String? ?? '',
    initialCapital: (j['initial_capital'] as num?)?.toDouble(),
    totalPnl: (j['total_pnl'] as num?)?.toDouble(),
    totalReturn: (j['total_return'] as num?)?.toDouble(),
    annualizedReturn: (j['annualized_return'] as num?)?.toDouble(),
    sharpeRatio: (j['sharpe_ratio'] as num?)?.toDouble(),
    totalTrades: (j['total_trades'] as num?)?.toInt(),
    dataStart: j['data_start'] as String?,
    dataEnd: j['data_end'] as String?,
    runDate: j['run_date'] as String?,
  );

  /// Best-effort display name for the strategy.
  String get displayName => strategy ?? strategySlug ?? runId;

  /// Handles both a bare JSON array and an object wrapping a list value.
  static List<ReportSummary> listFrom(dynamic raw) {
    List<dynamic> list;
    if (raw is List) {
      list = raw;
    } else if (raw is Map) {
      list = raw.values.whereType<List>().isNotEmpty
          ? raw.values.whereType<List>().first
          : const [];
    } else {
      list = const [];
    }
    return list
        .whereType<Map>()
        .map((e) => ReportSummary.fromJson(Map<String, dynamic>.from(e)))
        .toList();
  }
}
