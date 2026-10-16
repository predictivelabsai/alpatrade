import 'package:dio/dio.dart';

import 'package:alpatrade/models/auth_session.dart';
import 'package:alpatrade/services/api_client.dart';

class AuthException implements Exception {
  final String message;
  const AuthException(this.message);

  @override
  String toString() => message;
}

class AuthService {
  final ApiClient _client;

  AuthService(this._client);

  Future<AuthSession> signIn({
    required String email,
    required String password,
  }) {
    return _authenticate('/auth/login', {
      'email': email.trim(),
      'password': password,
    });
  }

  Future<AuthSession> register({
    required String email,
    required String password,
    String? displayName,
  }) {
    return _authenticate('/auth/register', {
      'email': email.trim(),
      'password': password,
      if (displayName != null && displayName.trim().isNotEmpty)
        'display_name': displayName.trim(),
    });
  }

  Future<AuthSession> _authenticate(
    String path,
    Map<String, dynamic> data,
  ) async {
    try {
      final json = await _client.post(path, data: data);
      final session = AuthSession.fromJson(json);
      if (session.token.isEmpty || session.userId.isEmpty) {
        throw const AuthException('The server returned an invalid session.');
      }
      return session;
    } on DioException catch (error) {
      final body = error.response?.data;
      final detail = body is Map ? body['detail'] : null;
      throw AuthException(
        detail?.toString() ?? 'Could not connect to AlpaTrade.',
      );
    }
  }
}
