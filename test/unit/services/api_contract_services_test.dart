import 'package:flutter_test/flutter_test.dart';

import 'package:alpatrade/services/activity_service.dart';
import 'package:alpatrade/services/api_client.dart';
import 'package:alpatrade/services/market_service.dart';
import 'package:alpatrade/services/positions_service.dart';

class _RecordingApiClient extends ApiClient {
  String? lastPath;
  Map<String, dynamic>? lastQuery;

  @override
  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? queryParameters,
  }) async {
    lastPath = path;
    lastQuery = queryParameters;
    if (path == '/v2/trades') return {'trades': [], 'total': 0};
    if (path == '/v2/positions') return {'positions': [], 'total': 0};
    return {'result': ''};
  }
}

void main() {
  test('activity uses the FastAPI type query alias', () async {
    final client = _RecordingApiClient();

    await ActivityService(client).getTrades(tradeType: 'backtest');

    expect(client.lastPath, '/v2/trades');
    expect(client.lastQuery, {'type': 'backtest'});
  });

  test('news uses the FastAPI ticker query name', () async {
    final client = _RecordingApiClient();

    await MarketService(client).getNews(symbol: 'AAPL');

    expect(client.lastPath, '/news');
    expect(client.lastQuery, {'ticker': 'AAPL'});
  });

  test('portfolio explicitly requests open positions', () async {
    final client = _RecordingApiClient();

    await PositionsService(client).getPositions();

    expect(client.lastPath, '/v2/positions');
    expect(client.lastQuery, {'status': 'open'});
  });
}
