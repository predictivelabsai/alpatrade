import 'package:carhero/services/api_client.dart';

class ContactService {
  final ApiClient _client;

  ContactService(this._client);

  Future<void> submit(String name, String email, String message) async {
    await _client.post(
      '/contact',
      data: {'name': name, 'email': email, 'message': message},
    );
  }
}
