import 'package:alpatrade/models/position.dart';
import 'package:alpatrade/services/api_client.dart';

class PositionsService {
  final ApiClient _client;
  PositionsService(this._client);

  Future<PositionsResponse> getPositions() async {
    final json = await _client.get('/v2/positions');
    return PositionsResponse.fromJson(json);
  }
}
