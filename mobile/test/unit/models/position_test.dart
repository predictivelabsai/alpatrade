import 'package:flutter_test/flutter_test.dart';
import 'package:alpatrade/models/position.dart';

void main() {
  group('Position.fromJson', () {
    test('parses a full position', () {
      final p = Position.fromJson({
        'id': 1,
        'run_id': 'r1',
        'symbol': 'MSFT',
        'side': 'long',
        'shares': 2.0,
        'avg_entry_price': 400.0,
        'current_price': 410.0,
        'market_value': 820.0,
        'unrealized_pnl': 20.0,
        'unrealized_pnl_pct': 2.5,
        'cost_basis': 800.0,
        'status': 'open',
      });
      expect(p.symbol, 'MSFT');
      expect(p.shares, 2.0);
      expect(p.unrealizedPnl, 20.0);
    });

    test('tolerates missing/null fields', () {
      final p = Position.fromJson({'run_id': 'r1', 'symbol': 'AAPL'});
      expect(p.symbol, 'AAPL');
      expect(p.avgEntryPrice, isNull);
      expect(p.shares, 0);
      expect(p.side, 'long');
    });
  });

  group('PositionsResponse totals', () {
    test('aggregates market value and unrealized P&L', () {
      final r = PositionsResponse.fromJson({
        'total': 2,
        'positions': [
          {
            'run_id': 'r1',
            'symbol': 'MSFT',
            'side': 'long',
            'shares': 2,
            'market_value': 820.0,
            'unrealized_pnl': 20.0,
            'cost_basis': 800.0,
            'status': 'open',
          },
          {
            'run_id': 'r1',
            'symbol': 'AAPL',
            'side': 'long',
            'shares': 1,
            'market_value': 200.0,
            'unrealized_pnl': -10.0,
            'cost_basis': 210.0,
            'status': 'open',
          },
        ],
      });
      expect(r.total, 2);
      expect(r.totalMarketValue, 1020.0);
      expect(r.totalUnrealizedPnl, 10.0);
      expect(r.totalCostBasis, 1010.0);
      expect(r.totalUnrealizedPnlPct, closeTo(10.0 / 1010.0 * 100, 1e-9));
    });

    test('null pct when no cost basis', () {
      const r = PositionsResponse(positions: [], total: 0);
      expect(r.totalUnrealizedPnlPct, isNull);
    });
  });
}
