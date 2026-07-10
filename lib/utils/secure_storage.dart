import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class SecureStorage {
  static const _storage = FlutterSecureStorage();
  static const _tokenKey = 'jwt_token';

  static Future<String?> getToken() async => _storage.read(key: _tokenKey);
  static Future<void> setToken(String token) async =>
      _storage.write(key: _tokenKey, value: token);
  static Future<void> deleteToken() async => _storage.delete(key: _tokenKey);
}
