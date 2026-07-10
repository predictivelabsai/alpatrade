import 'package:flutter_test/flutter_test.dart';
import 'package:mockito/annotations.dart';
import 'package:mockito/mockito.dart';

import 'package:carhero/services/api_client.dart';
import 'package:carhero/services/auth_service.dart';

@GenerateMocks([ApiClient])
import 'auth_service_test.mocks.dart';

void main() {
  late MockApiClient mockClient;
  late AuthService authService;

  setUp(() {
    mockClient = MockApiClient();
    authService = AuthService(mockClient);
  });

  group('AuthService.login', () {
    test('returns AuthResponse on success', () async {
      when(mockClient.post('/auth/login', data: anyNamed('data'))).thenAnswer(
        (_) async => {
          'token': 'jwt-123',
          'email': 'user@test.com',
          'name': 'Test',
          'user_id': 1,
        },
      );

      final auth = await authService.login('user@test.com', 'pass');

      expect(auth.token, 'jwt-123');
      expect(auth.email, 'user@test.com');
      expect(auth.userId, 1);

      verify(mockClient.post('/auth/login', data: anyNamed('data'))).called(1);
    });

    test('throws on API error', () async {
      when(
        mockClient.post('/auth/login', data: anyNamed('data')),
      ).thenThrow(Exception('Invalid credentials'));

      expect(() => authService.login('bad@test.com', 'wrong'), throwsException);
    });
  });

  group('AuthService.register', () {
    test('returns AuthResponse on success', () async {
      when(
        mockClient.post('/auth/register', data: anyNamed('data')),
      ).thenAnswer(
        (_) async => {
          'token': 'new-jwt',
          'email': 'new@test.com',
          'name': 'New User',
          'user_id': 2,
        },
      );

      final auth = await authService.register(
        'new@test.com',
        'pass',
        'New User',
      );

      expect(auth.token, 'new-jwt');
      expect(auth.name, 'New User');
    });
  });

  group('AuthService.me', () {
    test('returns UserInfo on success', () async {
      when(mockClient.get('/auth/me')).thenAnswer(
        (_) async => {'user_id': 1, 'email': 'user@test.com', 'name': 'Test'},
      );

      final user = await authService.me();

      expect(user.userId, 1);
      expect(user.email, 'user@test.com');
    });

    test('throws UnauthorizedException on 401', () async {
      when(mockClient.get('/auth/me')).thenThrow(const UnauthorizedException());

      expect(() => authService.me(), throwsA(isA<UnauthorizedException>()));
    });
  });
}
