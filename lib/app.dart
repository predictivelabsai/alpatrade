import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/router/app_router.dart';
import 'package:alpatrade/providers/locale_provider.dart';

class AlpaTradeApp extends ConsumerWidget {
  const AlpaTradeApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final localeCode = ref.watch(localeProvider);

    return MaterialApp.router(
      title: 'AlpaTrade',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      locale: Locale(localeCode),
      supportedLocales: const [
        Locale('en'),
        Locale('et'),
        Locale('de'),
        Locale('fr'),
        Locale('sv'),
        Locale('lv'),
        Locale('no'),
        Locale('da'),
        Locale('pl'),
        Locale('nl'),
        Locale('fi'),
        Locale('lt'),
      ],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      routerConfig: router,
    );
  }
}
