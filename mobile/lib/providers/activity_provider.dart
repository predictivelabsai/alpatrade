import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/models/run.dart';
import 'package:alpatrade/models/trade.dart';
import 'package:alpatrade/providers/api_provider.dart';
import 'package:alpatrade/services/activity_service.dart';

final activityServiceProvider = Provider<ActivityService>(
  (ref) => ActivityService(ref.watch(apiClientProvider)),
);

final tradesProvider = FutureProvider.family<TradesResponse, String>(
  (ref, tradeType) =>
      ref.watch(activityServiceProvider).getTrades(tradeType: tradeType),
);

final runsProvider = FutureProvider<RunsResponse>(
  (ref) => ref.watch(activityServiceProvider).getRuns(),
);
