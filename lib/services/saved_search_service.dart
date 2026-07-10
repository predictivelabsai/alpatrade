import 'package:carhero/models/saved_search.dart';
import 'package:carhero/services/api_client.dart';

class SavedSearchService {
  final ApiClient _client;

  SavedSearchService(this._client);

  Future<List<SavedSearch>> list() async {
    final data = await _client.getList('/saved-searches');
    return data
        .map((e) => SavedSearch.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<int?> create(
    String name,
    Map<String, dynamic> filters, {
    bool notifyEmail = false,
  }) async {
    final json = await _client.post(
      '/saved-searches',
      data: {'name': name, 'filters': filters, 'notify_email': notifyEmail},
    );
    return json['id'] as int?;
  }

  Future<void> delete(int searchId) async {
    await _client.delete('/saved-searches/$searchId');
  }

  Future<int> check(int searchId) async {
    final json = await _client.get('/saved-searches/$searchId/check');
    return json['new_count'] as int;
  }
}
