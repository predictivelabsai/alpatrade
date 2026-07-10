import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/saved_search.dart';
import 'package:carhero/services/saved_search_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final savedSearchServiceProvider = Provider<SavedSearchService>((ref) {
  return SavedSearchService(ref.read(apiClientProvider));
});

final savedSearchesProvider =
    AsyncNotifierProvider<SavedSearchesNotifier, List<SavedSearch>>(
      () => SavedSearchesNotifier(),
    );

class SavedSearchesNotifier extends AsyncNotifier<List<SavedSearch>> {
  @override
  Future<List<SavedSearch>> build() async {
    final isLoggedIn = ref.watch(isLoggedInProvider);
    if (!isLoggedIn) return [];
    return ref.read(savedSearchServiceProvider).list();
  }

  Future<void> create(
    String name,
    Map<String, dynamic> filters, {
    bool notifyEmail = false,
  }) async {
    await ref
        .read(savedSearchServiceProvider)
        .create(name, filters, notifyEmail: notifyEmail);
    ref.invalidateSelf();
  }

  Future<void> delete(int searchId) async {
    await ref.read(savedSearchServiceProvider).delete(searchId);
    ref.invalidateSelf();
  }
}
