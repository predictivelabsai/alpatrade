class AuthSession {
  final String token;
  final String userId;
  final String email;

  const AuthSession({
    required this.token,
    required this.userId,
    required this.email,
  });

  factory AuthSession.fromJson(Map<String, dynamic> json) {
    return AuthSession(
      token: (json['token'] ?? '').toString(),
      userId: (json['user_id'] ?? '').toString(),
      email: (json['email'] ?? '').toString(),
    );
  }
}
