import 'package:carhero/models/session.dart';
import 'package:carhero/services/api_client.dart';

class SessionService {
  final ApiClient _client;

  SessionService(this._client);

  Future<List<SessionSummary>> listSessions({int limit = 30}) async {
    final list = await _client.getList(
      '/sessions',
      queryParameters: {'limit': limit},
    );
    return list
        .map((e) => SessionSummary.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<SessionDetail> getSession(int sessionId) async {
    final json = await _client.get('/sessions/$sessionId');
    return SessionDetail.fromJson(json);
  }

  Future<void> deleteSession(int sessionId) async {
    await _client.delete('/sessions/$sessionId');
  }

  Future<ShareResponse> shareSession(int sessionId) async {
    final json = await _client.post('/sessions/$sessionId/share');
    return ShareResponse.fromJson(json);
  }
}
