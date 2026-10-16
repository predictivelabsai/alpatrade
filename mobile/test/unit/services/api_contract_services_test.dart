import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:alpatrade/services/activity_service.dart';
import 'package:alpatrade/services/api_client.dart';
import 'package:alpatrade/services/market_service.dart';
import 'package:alpatrade/services/positions_service.dart';
import 'package:alpatrade/services/auth_service.dart';

class _RecordingAdapter implements HttpClientAdapter {
  final int statusCode;
  final String responseJson;
  RequestOptions? request;

  _RecordingAdapter({this.statusCode = 200, this.responseJson = '{}'});

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    request = options;
    return ResponseBody.fromString(
      responseJson,
      statusCode,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

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

  test('authenticated API requests include the bearer token', () async {
    final adapter = _RecordingAdapter();
    final client = ApiClient(token: 'test-token', adapter: adapter);

    await client.get('/v2/status');

    expect(adapter.request?.headers['Authorization'], 'Bearer test-token');
  });

  test('a 401 clears the persisted session exactly once', () async {
    final adapter = _RecordingAdapter(
      statusCode: 401,
      responseJson: jsonEncode({'detail': 'Authentication required'}),
    );
    var unauthorizedCalls = 0;
    final client = ApiClient(
      token: 'expired-token',
      adapter: adapter,
      onUnauthorized: () => unauthorizedCalls++,
    );

    await expectLater(client.get('/v2/status'), throwsA(isA<DioException>()));

    expect(unauthorizedCalls, 1);
  });

  test('auth service parses and returns a server session', () async {
    final adapter = _RecordingAdapter(
      responseJson: jsonEncode({
        'token': 'jwt-token',
        'user_id': 'user-1',
        'email': 'tester@example.com',
      }),
    );
    final service = AuthService(ApiClient(adapter: adapter));

    final session = await service.signIn(
      email: ' tester@example.com ',
      password: 'secret12',
    );

    expect(session.token, 'jwt-token');
    expect(session.userId, 'user-1');
    expect(session.email, 'tester@example.com');
    expect(adapter.request?.path, '/auth/login');
    expect(adapter.request?.data, {
      'email': 'tester@example.com',
      'password': 'secret12',
    });
  });
}
