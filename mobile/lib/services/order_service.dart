import 'package:alpatrade/models/order.dart';
import 'package:alpatrade/services/api_client.dart';

class OrderService {
  final ApiClient _client;
  OrderService(this._client);

  Future<OrderResponse> placeOrder(OrderRequest req) async {
    final json = await _client.post('/v2/order', data: req.toJson());
    return OrderResponse.fromJson(json);
  }
}
