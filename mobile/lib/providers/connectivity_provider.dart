import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final connectivityProvider = StreamNotifierProvider<ConnectivityNotifier, bool>(
  () {
    return ConnectivityNotifier();
  },
);

class ConnectivityNotifier extends StreamNotifier<bool> {
  @override
  Stream<bool> build() {
    return Connectivity().onConnectivityChanged.map(
      (results) => !results.contains(ConnectivityResult.none),
    );
  }
}
