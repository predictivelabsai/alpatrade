import 'package:carhero/models/profile.dart';
import 'package:carhero/services/api_client.dart';

class ProfileService {
  final ApiClient _client;

  ProfileService(this._client);

  Future<UserProfile> getProfile() async {
    final json = await _client.get('/profile');
    return UserProfile.fromJson(json);
  }

  Future<void> updateProfile(UpdateProfileRequest request) async {
    await _client.post('/profile', data: request.toJson());
  }
}
