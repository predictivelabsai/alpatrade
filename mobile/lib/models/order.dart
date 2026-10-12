/// Request body for POST /v2/order (paper order — market or limit).
class OrderRequest {
  final String symbol;
  final double qty;
  final String side; // 'buy' | 'sell'
  final String orderType; // 'market' | 'limit'
  final double? limitPrice;
  final String timeInForce; // 'day' | 'gtc' | ...

  const OrderRequest({
    required this.symbol,
    required this.qty,
    this.side = 'buy',
    this.orderType = 'market',
    this.limitPrice,
    this.timeInForce = 'day',
  });

  Map<String, dynamic> toJson() => {
    'symbol': symbol,
    'qty': qty,
    'side': side,
    'order_type': orderType,
    if (limitPrice != null) 'limit_price': limitPrice,
    'time_in_force': timeInForce,
  };
}

/// Response from POST /v2/order.
class OrderResponse {
  final bool ok;
  final String? orderId;
  final String? symbol;
  final double? qty;
  final String? side;
  final String? orderType;
  final double? limitPrice;
  final String? status;
  final bool paper;
  final String? error;

  const OrderResponse({
    required this.ok,
    this.orderId,
    this.symbol,
    this.qty,
    this.side,
    this.orderType,
    this.limitPrice,
    this.status,
    this.paper = true,
    this.error,
  });

  factory OrderResponse.fromJson(Map<String, dynamic> j) => OrderResponse(
    ok: j['ok'] as bool? ?? false,
    orderId: j['order_id'] as String?,
    symbol: j['symbol'] as String?,
    qty: (j['qty'] as num?)?.toDouble(),
    side: j['side'] as String?,
    orderType: j['order_type'] as String?,
    limitPrice: (j['limit_price'] as num?)?.toDouble(),
    status: j['status'] as String?,
    paper: j['paper'] as bool? ?? true,
    error: j['error'] as String?,
  );
}
