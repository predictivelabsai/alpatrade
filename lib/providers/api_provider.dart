import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/providers/auth_provider.dart';
import 'package:alpatrade/services/api_client.dart';

/// Shared REST client. Public endpoints work without a session; protected
/// endpoints receive the stored bearer token and clear an expired session.
final apiClientProvider = Provider<ApiClient>((ref) {
  final session = ref.watch(authProvider).whenOrNull(data: (value) => value);
  return ApiClient(
    token: session?.token,
    onUnauthorized: () => ref.read(authProvider.notifier).signOut(),
  );
});
