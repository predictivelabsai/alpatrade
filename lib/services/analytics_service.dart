import 'package:carhero/models/analytics.dart';
import 'package:carhero/services/api_client.dart';

class AnalyticsService {
  final ApiClient _client;

  AnalyticsService(this._client);

  Future<AnalyticsResult> query(String question) async {
    final json = await _client.post(
      '/analytics/query',
      data: {'question': question},
    );
    return AnalyticsResult.fromJson(json);
  }
}
