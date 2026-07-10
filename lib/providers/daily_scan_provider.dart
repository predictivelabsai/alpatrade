import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/daily_scan.dart';
import 'package:carhero/services/daily_scan_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final dailyScanServiceProvider = Provider<DailyScanService>((ref) {
  return DailyScanService(ref.watch(apiClientProvider));
});

final dailyScanProvider = FutureProvider<DailyScanData>((ref) async {
  final service = ref.watch(dailyScanServiceProvider);
  return service.getDailyScan();
});
