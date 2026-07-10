import 'package:carhero/models/garage.dart';
import 'package:carhero/services/api_client.dart';

class GarageService {
  final ApiClient _client;

  GarageService(this._client);

  Future<List<GarageCar>> list() async {
    final data = await _client.getList('/garage');
    return data
        .map((e) => GarageCar.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<int?> addCar(AddGarageCarRequest car) async {
    final json = await _client.post('/garage', data: car.toJson());
    return json['id'] as int?;
  }

  Future<void> deleteCar(int carId) async {
    await _client.delete('/garage/$carId');
  }

  Future<Valuation> getValuation(int carId) async {
    final json = await _client.get('/garage/$carId/valuation');
    return Valuation.fromJson(json);
  }

  Future<TcoCost> getTco(int carId) async {
    final json = await _client.get('/garage/$carId/tco');
    return TcoCost.fromJson(json);
  }
}
