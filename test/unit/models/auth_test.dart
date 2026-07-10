import 'package:flutter_test/flutter_test.dart';
import 'package:carhero/models/auth.dart';

void main() {
  group('AuthResponse', () {
    test('fromJson parses complete response', () {
      final json = {
        'token': 'jwt-token-123',
        'email': 'test@example.com',
        'name': 'Test User',
        'user_id': 42,
      };

      final auth = AuthResponse.fromJson(json);

      expect(auth.token, 'jwt-token-123');
      expect(auth.email, 'test@example.com');
      expect(auth.name, 'Test User');
      expect(auth.userId, 42);
    });

    test('fromJson handles null name', () {
      final json = {
        'token': 'tok',
        'email': 'a@b.com',
        'name': null,
        'user_id': 1,
      };

      final auth = AuthResponse.fromJson(json);
      expect(auth.name, '');
    });

    test('fromJson handles missing name', () {
      final json = {'token': 'tok', 'email': 'a@b.com', 'user_id': 1};

      final auth = AuthResponse.fromJson(json);
      expect(auth.name, '');
    });

    test('toJson round-trips correctly', () {
      const auth = AuthResponse(
        token: 'tok',
        email: 'a@b.com',
        name: 'Bob',
        userId: 7,
      );

      final json = auth.toJson();
      final restored = AuthResponse.fromJson(json);

      expect(restored.token, auth.token);
      expect(restored.email, auth.email);
      expect(restored.name, auth.name);
      expect(restored.userId, auth.userId);
    });
  });

  group('UserInfo', () {
    test('fromJson parses correctly', () {
      final json = {'user_id': 5, 'email': 'user@test.com', 'name': 'Jane'};

      final user = UserInfo.fromJson(json);
      expect(user.userId, 5);
      expect(user.email, 'user@test.com');
      expect(user.name, 'Jane');
    });

    test('fromJson defaults name to empty string', () {
      final json = {'user_id': 1, 'email': 'x@y.com'};
      final user = UserInfo.fromJson(json);
      expect(user.name, '');
    });
  });

  group('LoginRequest', () {
    test('toJson produces correct keys', () {
      const req = LoginRequest(email: 'a@b.com', password: 'secret');
      final json = req.toJson();

      expect(json['email'], 'a@b.com');
      expect(json['password'], 'secret');
      expect(json.length, 2);
    });
  });

  group('RegisterRequest', () {
    test('toJson includes name', () {
      const req = RegisterRequest(
        email: 'a@b.com',
        password: 'pass123',
        name: 'Alice',
      );
      final json = req.toJson();

      expect(json['email'], 'a@b.com');
      expect(json['password'], 'pass123');
      expect(json['name'], 'Alice');
    });

    test('toJson defaults name to empty', () {
      const req = RegisterRequest(email: 'a@b.com', password: 'p');
      expect(req.toJson()['name'], '');
    });
  });
}
