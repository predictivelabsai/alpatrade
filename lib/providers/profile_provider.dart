import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/profile.dart';
import 'package:carhero/services/profile_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final profileServiceProvider = Provider<ProfileService>((ref) {
  return ProfileService(ref.read(apiClientProvider));
});

final profileProvider = AsyncNotifierProvider<ProfileNotifier, UserProfile?>(
  () => ProfileNotifier(),
);

class ProfileNotifier extends AsyncNotifier<UserProfile?> {
  @override
  Future<UserProfile?> build() async {
    final isLoggedIn = ref.watch(isLoggedInProvider);
    if (!isLoggedIn) return null;
    return ref.read(profileServiceProvider).getProfile();
  }

  Future<void> updateProfile(UpdateProfileRequest request) async {
    await ref.read(profileServiceProvider).updateProfile(request);
    ref.invalidateSelf();
  }
}
