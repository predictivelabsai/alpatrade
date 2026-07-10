import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/garage.dart';
import 'package:carhero/services/garage_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final garageServiceProvider = Provider<GarageService>((ref) {
  return GarageService(ref.read(apiClientProvider));
});

final garageProvider = AsyncNotifierProvider<GarageNotifier, List<GarageCar>>(
  () => GarageNotifier(),
);

class GarageNotifier extends AsyncNotifier<List<GarageCar>> {
  @override
  Future<List<GarageCar>> build() async {
    final isLoggedIn = ref.watch(isLoggedInProvider);
    if (!isLoggedIn) return [];
    return ref.read(garageServiceProvider).list();
  }

  Future<void> addCar(AddGarageCarRequest car) async {
    await ref.read(garageServiceProvider).addCar(car);
    ref.invalidateSelf();
  }

  Future<void> deleteCar(int carId) async {
    await ref.read(garageServiceProvider).deleteCar(carId);
    ref.invalidateSelf();
  }
}
