import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/services/api_client.dart';

/// Single shared anonymous REST client for all feature services.
final apiClientProvider = Provider<ApiClient>((ref) => ApiClient());
