import 'package:alpatrade/models/pnl.dart';
import 'package:alpatrade/models/strategy.dart';
import 'package:alpatrade/services/api_client.dart';

class StrategiesService {
  final ApiClient _client;
  StrategiesService(this._client);

  Future<List<TopStrategy>> getTop() async {
    final json = await _client.getList('/v2/top');
    return TopStrategy.listFromJson(json);
  }

  Future<List<ReportSummary>> getReports() async {
    final json = await _client.getList('/v2/report');
    return ReportSummary.listFrom(json);
  }

  Future<PnlBreakdown> getPnl(String runId) async {
    final json = await _client.get('/v2/pnl/$runId');
    return PnlBreakdown.fromJson(json);
  }
}
