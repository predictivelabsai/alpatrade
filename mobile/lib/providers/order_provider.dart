import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/providers/api_provider.dart';
import 'package:alpatrade/services/order_service.dart';

final orderServiceProvider = Provider<OrderService>(
  (ref) => OrderService(ref.watch(apiClientProvider)),
);
