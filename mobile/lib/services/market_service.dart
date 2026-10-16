import 'package:alpatrade/services/api_client.dart';

/// Thin wrapper over the AlpaTrade market/data endpoints. Returns the raw
/// markdown `result` strings for news/movers and the full status map.
class MarketService {
  final ApiClient _client;

  MarketService(this._client);

  /// GET `/news?ticker=SYM` -> `{"result": "markdown"}` (ticker optional).
  Future<String> getNews({String? symbol}) async {
    final data = await _client.get(
      '/news',
      queryParameters: (symbol != null && symbol.isNotEmpty)
          ? {'ticker': symbol}
          : null,
    );
    return (data['result'] ?? '') as String;
  }

  /// GET `/movers` -> `{"result": "markdown"}`.
  Future<String> getMovers() async {
    final data = await _client.get('/movers');
    return (data['result'] ?? '') as String;
  }

  /// GET /v2/status -> agent run status map.
  Future<Map<String, dynamic>> getStatus() async {
    return _client.get('/v2/status');
  }
}
