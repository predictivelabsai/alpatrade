/// One executed trade — mirrors TradeItem in the AlpaTrade v2 API.
class Trade {
  final int? id;
  final String runId;
  final String tradeType; // 'paper' | 'backtest'
  final String? symbol;
  final String? direction; // 'buy' | 'sell'
  final double? shares;
  final String? entryTime;
  final String? exitTime;
  final double? entryPrice;
  final double? exitPrice;
  final double? targetPrice;
  final double? stopPrice;
  final bool? hitTarget;
  final bool? hitStop;
  final double? pnl;
  final double? pnlPct;
  final double? totalFees;
  final String? reason;

  const Trade({
    this.id,
    required this.runId,
    required this.tradeType,
    this.symbol,
    this.direction,
    this.shares,
    this.entryTime,
    this.exitTime,
    this.entryPrice,
    this.exitPrice,
    this.targetPrice,
    this.stopPrice,
    this.hitTarget,
    this.hitStop,
    this.pnl,
    this.pnlPct,
    this.totalFees,
    this.reason,
  });

  factory Trade.fromJson(Map<String, dynamic> j) => Trade(
    id: (j['id'] as num?)?.toInt(),
    runId: j['run_id'] as String? ?? '',
    tradeType: j['trade_type'] as String? ?? 'paper',
    symbol: j['symbol'] as String?,
    direction: j['direction'] as String?,
    shares: (j['shares'] as num?)?.toDouble(),
    entryTime: j['entry_time'] as String?,
    exitTime: j['exit_time'] as String?,
    entryPrice: (j['entry_price'] as num?)?.toDouble(),
    exitPrice: (j['exit_price'] as num?)?.toDouble(),
    targetPrice: (j['target_price'] as num?)?.toDouble(),
    stopPrice: (j['stop_price'] as num?)?.toDouble(),
    hitTarget: j['hit_target'] as bool?,
    hitStop: j['hit_stop'] as bool?,
    pnl: (j['pnl'] as num?)?.toDouble(),
    pnlPct: (j['pnl_pct'] as num?)?.toDouble(),
    totalFees: (j['total_fees'] as num?)?.toDouble(),
    reason: j['reason'] as String?,
  );
}

/// Response envelope for GET /v2/trades.
class TradesResponse {
  final List<Trade> trades;
  final int total;

  const TradesResponse({required this.trades, required this.total});

  factory TradesResponse.fromJson(Map<String, dynamic> j) => TradesResponse(
    trades: ((j['trades'] as List?) ?? [])
        .map((e) => Trade.fromJson(e as Map<String, dynamic>))
        .toList(),
    total: (j['total'] as num?)?.toInt() ?? 0,
  );
}
