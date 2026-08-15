import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/app.dart';
import 'package:alpatrade/services/api_client.dart';

Duration? appProviderRetry(int retryCount, Object error) {
  if (isUnauthorizedError(error)) return null;
  return ProviderContainer.defaultRetry(retryCount, error, maxRetries: 3);
}

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(retry: appProviderRetry, child: AlpaTradeApp()));
}
