class Validators {
  static String? email(String? v) {
    if (v == null || v.isEmpty) return 'Email is required';
    if (!v.contains('@') || !v.contains('.')) return 'Invalid email';
    return null;
  }

  static String? password(String? v) {
    if (v == null || v.isEmpty) return 'Password is required';
    if (v.length < 6) return 'Must be at least 6 characters';
    return null;
  }

  static String? required(String? v) {
    if (v == null || v.trim().isEmpty) return 'This field is required';
    return null;
  }
}
