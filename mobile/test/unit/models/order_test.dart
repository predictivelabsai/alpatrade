import 'package:flutter_test/flutter_test.dart';
import 'package:alpatrade/models/order.dart';

void main() {
  group('OrderRequest.toJson', () {
    test('limit order includes limit_price', () {
      final j = const OrderRequest(
        symbol: 'AAPL',
        qty: 10,
        side: 'buy',
        orderType: 'limit',
        limitPrice: 150,
      ).toJson();
      expect(j['symbol'], 'AAPL');
      expect(j['qty'], 10);
      expect(j['side'], 'buy');
      expect(j['order_type'], 'limit');
      expect(j['limit_price'], 150);
      expect(j['time_in_force'], 'day');
    });

    test('market order omits limit_price', () {
      final j = const OrderRequest(symbol: 'MSFT', qty: 1).toJson();
      expect(j.containsKey('limit_price'), isFalse);
      expect(j['side'], 'buy');
      expect(j['order_type'], 'market');
    });
  });

  group('OrderResponse.fromJson', () {
    test('parses success', () {
      final r = OrderResponse.fromJson({
        'ok': true,
        'order_id': 'abc',
        'symbol': 'AAPL',
        'qty': 1.0,
        'side': 'buy',
        'order_type': 'market',
        'status': 'OrderStatus.PENDING_NEW',
        'paper': true,
      });
      expect(r.ok, isTrue);
      expect(r.orderId, 'abc');
      expect(r.status, 'OrderStatus.PENDING_NEW');
    });

    test('parses rejection with error', () {
      final r = OrderResponse.fromJson({
        'ok': false,
        'error': 'potential wash trade detected',
        'paper': true,
      });
      expect(r.ok, isFalse);
      expect(r.error, contains('wash trade'));
      expect(r.orderId, isNull);
    });
  });
}
