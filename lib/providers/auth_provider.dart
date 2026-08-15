import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:alpatrade/models/auth_session.dart';
import 'package:alpatrade/services/api_client.dart';
import 'package:alpatrade/services/auth_service.dart';

const _tokenKey = 'alpatrade.auth.token';
const _userIdKey = 'alpatrade.auth.user_id';
const _emailKey = 'alpatrade.auth.email';

final authServiceProvider = Provider<AuthService>(
  (ref) => AuthService(ApiClient()),
);

final authProvider = AsyncNotifierProvider<AuthNotifier, AuthSession?>(
  AuthNotifier.new,
);

class AuthNotifier extends AsyncNotifier<AuthSession?> {
  @override
  Future<AuthSession?> build() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_tokenKey) ?? '';
    final userId = prefs.getString(_userIdKey) ?? '';
    final email = prefs.getString(_emailKey) ?? '';
    if (token.isEmpty || userId.isEmpty) return null;
    return AuthSession(token: token, userId: userId, email: email);
  }

  Future<bool> signIn({required String email, required String password}) {
    return _authenticate(
      () => ref
          .read(authServiceProvider)
          .signIn(email: email, password: password),
    );
  }

  Future<bool> register({
    required String email,
    required String password,
    String? displayName,
  }) {
    return _authenticate(
      () => ref
          .read(authServiceProvider)
          .register(email: email, password: password, displayName: displayName),
    );
  }

  Future<bool> _authenticate(Future<AuthSession> Function() request) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {
      final session = await request();
      await _persist(session);
      return session;
    });
    return state.when(
      data: (_) => true,
      error: (_, _) => false,
      loading: () => false,
    );
  }

  Future<void> signOut() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    await prefs.remove(_userIdKey);
    await prefs.remove(_emailKey);
    state = const AsyncData(null);
  }

  Future<void> _persist(AuthSession session) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, session.token);
    await prefs.setString(_userIdKey, session.userId);
    await prefs.setString(_emailKey, session.email);
  }
}
