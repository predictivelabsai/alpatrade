import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/providers/api_provider.dart';
import 'package:alpatrade/services/market_service.dart';

final marketServiceProvider = Provider<MarketService>(
  (ref) => MarketService(ref.watch(apiClientProvider)),
);

/// Market movers markdown.
final moversProvider = FutureProvider<String>(
  (ref) => ref.watch(marketServiceProvider).getMovers(),
);

/// Market news markdown, filtered by an optional symbol (null = all).
final newsProvider = FutureProvider.family<String, String?>(
  (ref, symbol) => ref.watch(marketServiceProvider).getNews(symbol: symbol),
);

/// Agent run status.
final statusProvider = FutureProvider<Map<String, dynamic>>(
  (ref) => ref.watch(marketServiceProvider).getStatus(),
);
