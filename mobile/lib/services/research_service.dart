import 'package:alpatrade/services/api_client.dart';

class ResearchService {
  final ApiClient client;
  ResearchService(this.client);

  Future<Map<String, dynamic>> leaderboard({
    String query = '',
    String kind = '',
  }) => client.get(
    '/v2/leaderboard',
    queryParameters: {'q': query, 'kind': kind},
  );
  Future<Map<String, dynamic>> backtest(int id) =>
      client.post('/v2/strategies/$id/backtest');
  Future<Map<String, dynamic>> backtestStatus(String id) =>
      client.get('/v2/strategy-backtests/$id');
  Future<Map<String, dynamic>> strategies() => client.get('/v2/strategies');
  Future<Map<String, dynamic>> strategy(int id) =>
      client.get('/v2/strategies/$id');
  Future<Map<String, dynamic>> clone(int id) =>
      client.post('/v2/strategies/$id/clone');
  Future<Map<String, dynamic>> funds({
    String query = '',
    String holds = '',
    String period = '',
    String minAum = '',
    String sort = 'aum',
  }) => client.get(
    '/v2/hedge-funds',
    queryParameters: {
      'q': query,
      'holds': holds,
      'period': period,
      'min_aum': minAum,
      'sort': sort,
    },
  );
  Future<Map<String, dynamic>> performance(String method) => client.get(
    '/v2/hedge-funds/performance',
    queryParameters: {'method': method},
  );
  Future<Map<String, dynamic>> activists(String ticker) => client.get(
    '/v2/hedge-funds/activists',
    queryParameters: {'ticker': ticker},
  );
  Future<Map<String, dynamic>> ipos({bool pipeline = false}) =>
      client.get(pipeline ? '/v2/ipos/pipeline' : '/v2/ipos');
  Future<List<dynamic>> advisor() => client.getList('/v2/advisor/reports');
}
