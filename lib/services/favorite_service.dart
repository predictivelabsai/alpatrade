import 'package:carhero/models/favorite.dart';
import 'package:carhero/services/api_client.dart';

class FavoriteService {
  final ApiClient _client;

  FavoriteService(this._client);

  Future<List<Favorite>> list() async {
    final data = await _client.getList('/favorites');
    return data
        .map((e) => Favorite.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> add(int listingId) async {
    await _client.post('/favorites', data: {'listing_id': listingId});
  }

  Future<void> remove(int favoriteId) async {
    await _client.delete('/favorites/$favoriteId');
  }

  Future<void> updateNote(int favoriteId, String note) async {
    await _client.post('/favorites/$favoriteId/note', data: {'note': note});
  }
}
