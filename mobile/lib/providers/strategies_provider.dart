import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/models/pnl.dart';
import 'package:alpatrade/models/strategy.dart';
import 'package:alpatrade/providers/api_provider.dart';
import 'package:alpatrade/services/strategies_service.dart';

final strategiesServiceProvider = Provider<StrategiesService>(
  (ref) => StrategiesService(ref.watch(apiClientProvider)),
);

final topStrategiesProvider = FutureProvider<List<TopStrategy>>(
  (ref) => ref.watch(strategiesServiceProvider).getTop(),
);

final reportsProvider = FutureProvider<List<ReportSummary>>(
  (ref) => ref.watch(strategiesServiceProvider).getReports(),
);

final pnlProvider = FutureProvider.family<PnlBreakdown, String>(
  (ref, runId) => ref.watch(strategiesServiceProvider).getPnl(runId),
);
