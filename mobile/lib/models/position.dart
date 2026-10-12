/// One open paper position — mirrors PositionItem in swagger.json.
class Position {
  final int? id;
  final String runId;
  final String symbol;
  final String side; // 'long' | 'short'
  final double shares;
  final double? avgEntryPrice;
  final double? currentPrice;
  final double? marketValue;
  final double? unrealizedPnl;
  final double? unrealizedPnlPct;
  final double? costBasis;
  final String status;
  final String? openedAt;
  final String? closedAt;

  const Position({
    this.id,
    required this.runId,
    required this.symbol,
    required this.side,
    required this.shares,
    this.avgEntryPrice,
    this.currentPrice,
    this.marketValue,
    this.unrealizedPnl,
    this.unrealizedPnlPct,
    this.costBasis,
    required this.status,
    this.openedAt,
    this.closedAt,
  });

  factory Position.fromJson(Map<String, dynamic> j) => Position(
    id: (j['id'] as num?)?.toInt(),
    runId: j['run_id'] as String? ?? '',
    symbol: j['symbol'] as String? ?? '',
    side: j['side'] as String? ?? 'long',
    shares: (j['shares'] as num?)?.toDouble() ?? 0,
    avgEntryPrice: (j['avg_entry_price'] as num?)?.toDouble(),
    currentPrice: (j['current_price'] as num?)?.toDouble(),
    marketValue: (j['market_value'] as num?)?.toDouble(),
    unrealizedPnl: (j['unrealized_pnl'] as num?)?.toDouble(),
    unrealizedPnlPct: (j['unrealized_pnl_pct'] as num?)?.toDouble(),
    costBasis: (j['cost_basis'] as num?)?.toDouble(),
    status: j['status'] as String? ?? 'open',
    openedAt: j['opened_at'] as String?,
    closedAt: j['closed_at'] as String?,
  );
}

/// Response envelope for GET /v2/positions, with client-side account totals.
class PositionsResponse {
  final List<Position> positions;
  final int total;

  const PositionsResponse({required this.positions, required this.total});

  factory PositionsResponse.fromJson(Map<String, dynamic> j) =>
      PositionsResponse(
        positions: ((j['positions'] as List?) ?? [])
            .map((e) => Position.fromJson(e as Map<String, dynamic>))
            .toList(),
        total: (j['total'] as num?)?.toInt() ?? 0,
      );

  double get totalMarketValue =>
      positions.fold(0, (s, p) => s + (p.marketValue ?? 0));

  double get totalUnrealizedPnl =>
      positions.fold(0, (s, p) => s + (p.unrealizedPnl ?? 0));

  double get totalCostBasis =>
      positions.fold(0, (s, p) => s + (p.costBasis ?? 0));

  double? get totalUnrealizedPnlPct {
    final cost = totalCostBasis;
    if (cost == 0) return null;
    return totalUnrealizedPnl / cost * 100;
  }
}
