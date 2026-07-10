import 'package:carhero/models/daily_scan.dart';
import 'package:carhero/services/api_client.dart';

class DailyScanService {
  final ApiClient _client;

  DailyScanService(this._client);

  Future<DailyScanData> getDailyScan() async {
    final json = await _client.get('/daily-scan');
    return DailyScanData.fromJson(json);
  }
}
