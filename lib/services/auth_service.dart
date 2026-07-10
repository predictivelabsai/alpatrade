import 'package:carhero/models/auth.dart';
import 'package:carhero/services/api_client.dart';

class AuthService {
  final ApiClient _client;

  AuthService(this._client);

  Future<AuthResponse> login(String email, String password) async {
    final json = await _client.post(
      '/auth/login',
      data: LoginRequest(email: email, password: password).toJson(),
    );
    return AuthResponse.fromJson(json);
  }

  Future<AuthResponse> register(
    String email,
    String password,
    String name,
  ) async {
    final json = await _client.post(
      '/auth/register',
      data: RegisterRequest(
        email: email,
        password: password,
        name: name,
      ).toJson(),
    );
    return AuthResponse.fromJson(json);
  }

  Future<AuthResponse> googleSignIn(String idToken) async {
    final json = await _client.post(
      '/auth/google',
      data: {'id_token': idToken},
    );
    return AuthResponse.fromJson(json);
  }

  Future<UserInfo> me() async {
    final json = await _client.get('/auth/me');
    return UserInfo.fromJson(json);
  }
}
