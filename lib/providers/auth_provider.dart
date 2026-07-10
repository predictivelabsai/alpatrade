import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/auth.dart';
import 'package:carhero/services/api_client.dart';
import 'package:carhero/services/auth_service.dart';
import 'package:carhero/utils/secure_storage.dart';

// ApiClient provider - depends on auth token
final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(getToken: () => ref.read(authProvider).value?.token);
});

// Service providers
final authServiceProvider = Provider<AuthService>((ref) {
  return AuthService(ref.read(apiClientProvider));
});

// Auth state - AsyncNotifier that manages login/register/logout
final authProvider = AsyncNotifierProvider<AuthNotifier, AuthResponse?>(
  () => AuthNotifier(),
);

class AuthNotifier extends AsyncNotifier<AuthResponse?> {
  @override
  Future<AuthResponse?> build() async {
    // Try to restore from secure storage
    final token = await SecureStorage.getToken();
    if (token == null) return null;
    try {
      final service = ref.read(authServiceProvider);
      final user = await service.me();
      return AuthResponse(
        token: token,
        email: user.email,
        name: user.name,
        userId: user.userId,
      );
    } catch (_) {
      await SecureStorage.deleteToken();
      return null;
    }
  }

  Future<void> login(String email, String password) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final service = ref.read(authServiceProvider);
      final auth = await service.login(email, password);
      await SecureStorage.setToken(auth.token);
      return auth;
    });
  }

  Future<void> register(String email, String password, String name) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final service = ref.read(authServiceProvider);
      final auth = await service.register(email, password, name);
      await SecureStorage.setToken(auth.token);
      return auth;
    });
  }

  Future<void> googleSignIn(String idToken) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final service = ref.read(authServiceProvider);
      final auth = await service.googleSignIn(idToken);
      await SecureStorage.setToken(auth.token);
      return auth;
    });
  }

  Future<void> logout() async {
    await SecureStorage.deleteToken();
    state = const AsyncValue.data(null);
  }
}

// Convenience providers
final isLoggedInProvider = Provider<bool>((ref) {
  return ref.watch(authProvider).value != null;
});

final currentTokenProvider = Provider<String?>((ref) {
  return ref.watch(authProvider).value?.token;
});
