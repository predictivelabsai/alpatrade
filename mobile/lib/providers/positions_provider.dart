import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:alpatrade/models/position.dart';
import 'package:alpatrade/providers/api_provider.dart';
import 'package:alpatrade/services/positions_service.dart';

final positionsServiceProvider = Provider<PositionsService>(
  (ref) => PositionsService(ref.watch(apiClientProvider)),
);

final positionsProvider = FutureProvider<PositionsResponse>(
  (ref) => ref.watch(positionsServiceProvider).getPositions(),
);
