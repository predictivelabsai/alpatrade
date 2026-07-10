import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/models/analytics.dart';
import 'package:carhero/services/analytics_service.dart';
import 'package:carhero/providers/auth_provider.dart';

final analyticsServiceProvider = Provider<AnalyticsService>((ref) {
  return AnalyticsService(ref.read(apiClientProvider));
});

enum AnalyticsStatus { idle, loading, result, error }

class AnalyticsState {
  final AnalyticsStatus status;
  final String query;
  final AnalyticsResult? result;
  final String? error;

  const AnalyticsState({
    this.status = AnalyticsStatus.idle,
    this.query = '',
    this.result,
    this.error,
  });

  AnalyticsState copyWith({
    AnalyticsStatus? status,
    String? query,
    AnalyticsResult? result,
    String? error,
  }) => AnalyticsState(
    status: status ?? this.status,
    query: query ?? this.query,
    result: result ?? this.result,
    error: error,
  );
}

final analyticsProvider = NotifierProvider<AnalyticsNotifier, AnalyticsState>(
  AnalyticsNotifier.new,
);

class AnalyticsNotifier extends Notifier<AnalyticsState> {
  @override
  AnalyticsState build() => const AnalyticsState();

  Future<void> runQuery(String question) async {
    state = state.copyWith(
      status: AnalyticsStatus.loading,
      query: question,
      error: null,
    );

    try {
      final service = ref.read(analyticsServiceProvider);
      final result = await service.query(question);
      state = state.copyWith(status: AnalyticsStatus.result, result: result);
    } catch (e) {
      state = state.copyWith(
        status: AnalyticsStatus.error,
        error: e.toString(),
      );
    }
  }

  void reset() {
    state = const AnalyticsState();
  }
}
