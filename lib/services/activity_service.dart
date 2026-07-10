import 'package:alpatrade/models/run.dart';
import 'package:alpatrade/models/trade.dart';
import 'package:alpatrade/services/api_client.dart';

class ActivityService {
  final ApiClient _client;
  ActivityService(this._client);

  Future<TradesResponse> getTrades({String tradeType = 'paper'}) async {
    final json = await _client.get(
      '/v2/trades',
      queryParameters: {'trade_type': tradeType},
    );
    return TradesResponse.fromJson(json);
  }

  Future<RunsResponse> getRuns() async {
    final json = await _client.get('/v2/runs');
    return RunsResponse.fromJson(json);
  }
}
