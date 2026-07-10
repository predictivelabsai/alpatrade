import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/session.dart';
import 'package:carhero/services/session_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final sessionServiceProvider = Provider<SessionService>((ref) {
  return SessionService(ref.read(apiClientProvider));
});

final sessionsProvider = FutureProvider<List<SessionSummary>>((ref) async {
  final service = ref.read(sessionServiceProvider);
  return service.listSessions();
});
