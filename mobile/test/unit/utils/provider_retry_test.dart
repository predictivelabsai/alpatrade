import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:alpatrade/main.dart' show appProviderRetry;
import 'package:alpatrade/services/api_client.dart';

void main() {
  test('authentication failures are not retried', () {
    expect(appProviderRetry(0, const UnauthorizedException()), isNull);
  });

  test('Dio-wrapped authentication failures are not retried', () {
    final error = DioException(
      requestOptions: RequestOptions(path: '/v2/positions'),
      error: const UnauthorizedException(),
      type: DioExceptionType.badResponse,
    );

    expect(appProviderRetry(0, error), isNull);
  });

  test('transient failures retain bounded retry behavior', () {
    expect(appProviderRetry(0, Exception('temporary')), isNotNull);
    expect(appProviderRetry(3, Exception('temporary')), isNull);
  });
}
