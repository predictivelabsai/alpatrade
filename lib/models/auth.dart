class AuthResponse {
  final String token;
  final String email;
  final String name;
  final int userId;

  const AuthResponse({
    required this.token,
    required this.email,
    this.name = '',
    required this.userId,
  });

  factory AuthResponse.fromJson(Map<String, dynamic> json) => AuthResponse(
    token: json['token'] as String,
    email: json['email'] as String,
    name: json['name'] as String? ?? '',
    userId: json['user_id'] as int,
  );

  Map<String, dynamic> toJson() => {
    'token': token,
    'email': email,
    'name': name,
    'user_id': userId,
  };
}

class UserInfo {
  final int userId;
  final String email;
  final String name;

  const UserInfo({required this.userId, required this.email, this.name = ''});

  factory UserInfo.fromJson(Map<String, dynamic> json) => UserInfo(
    userId: json['user_id'] as int,
    email: json['email'] as String,
    name: json['name'] as String? ?? '',
  );
}

class LoginRequest {
  final String email;
  final String password;
  const LoginRequest({required this.email, required this.password});

  Map<String, dynamic> toJson() => {'email': email, 'password': password};
}

class RegisterRequest {
  final String email;
  final String password;
  final String name;
  const RegisterRequest({
    required this.email,
    required this.password,
    this.name = '',
  });

  Map<String, dynamic> toJson() => {
    'email': email,
    'password': password,
    'name': name,
  };
}
