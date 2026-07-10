import 'package:flutter_test/flutter_test.dart';
import 'package:mockito/annotations.dart';
import 'package:mockito/mockito.dart';

import 'package:carhero/services/api_client.dart';
import 'package:carhero/services/favorite_service.dart';

@GenerateMocks([ApiClient])
import 'favorite_service_test.mocks.dart';

void main() {
  late MockApiClient mockClient;
  late FavoriteService service;

  setUp(() {
    mockClient = MockApiClient();
    service = FavoriteService(mockClient);
  });

  group('FavoriteService.list', () {
    test('returns list of favorites', () async {
      when(mockClient.getList('/favorites')).thenAnswer(
        (_) async => [
          {
            'id': 1,
            'listing_id': 100,
            'make': 'BMW',
            'model': 'M3',
            'year': 2021,
            'price_eur': 65000,
          },
          {
            'id': 2,
            'listing_id': 200,
            'make': 'Porsche',
            'model': '911',
            'year': 2020,
            'price_eur': 95000,
          },
        ],
      );

      final favorites = await service.list();

      expect(favorites, hasLength(2));
      expect(favorites[0].make, 'BMW');
      expect(favorites[1].make, 'Porsche');
    });

    test('returns empty list when no favorites', () async {
      when(mockClient.getList('/favorites')).thenAnswer((_) async => []);

      final favorites = await service.list();
      expect(favorites, isEmpty);
    });
  });

  group('FavoriteService.add', () {
    test('calls correct endpoint', () async {
      when(
        mockClient.post('/favorites', data: anyNamed('data')),
      ).thenAnswer((_) async => {'id': 1});

      await service.add(42);

      verify(
        mockClient.post(
          '/favorites',
          data: argThat(equals({'listing_id': 42}), named: 'data'),
        ),
      ).called(1);
    });
  });

  group('FavoriteService.remove', () {
    test('calls correct endpoint', () async {
      when(mockClient.delete('/favorites/5')).thenAnswer((_) async {});

      await service.remove(5);

      verify(mockClient.delete('/favorites/5')).called(1);
    });
  });

  group('FavoriteService.updateNote', () {
    test('calls correct endpoint with note', () async {
      when(
        mockClient.post('/favorites/3/note', data: anyNamed('data')),
      ).thenAnswer((_) async => {});

      await service.updateNote(3, 'Great price');

      verify(
        mockClient.post(
          '/favorites/3/note',
          data: argThat(equals({'note': 'Great price'}), named: 'data'),
        ),
      ).called(1);
    });
  });
}
