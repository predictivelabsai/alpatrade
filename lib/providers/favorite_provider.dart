import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/favorite.dart';
import 'package:carhero/services/favorite_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final favoriteServiceProvider = Provider<FavoriteService>((ref) {
  return FavoriteService(ref.read(apiClientProvider));
});

final favoritesProvider =
    AsyncNotifierProvider<FavoritesNotifier, List<Favorite>>(
      () => FavoritesNotifier(),
    );

class FavoritesNotifier extends AsyncNotifier<List<Favorite>> {
  @override
  Future<List<Favorite>> build() async {
    final isLoggedIn = ref.watch(isLoggedInProvider);
    if (!isLoggedIn) return [];
    return ref.read(favoriteServiceProvider).list();
  }

  Future<void> add(int listingId) async {
    await ref.read(favoriteServiceProvider).add(listingId);
    ref.invalidateSelf();
  }

  Future<void> remove(int favoriteId) async {
    await ref.read(favoriteServiceProvider).remove(favoriteId);
    ref.invalidateSelf();
  }

  Future<void> updateNote(int favoriteId, String note) async {
    await ref.read(favoriteServiceProvider).updateNote(favoriteId, note);
    ref.invalidateSelf();
  }
}
