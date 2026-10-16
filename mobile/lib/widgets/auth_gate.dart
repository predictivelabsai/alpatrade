import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/providers/auth_provider.dart';

class AuthGate extends ConsumerWidget {
  final String title;
  final String returnTo;
  final Widget child;

  const AuthGate({
    super.key,
    required this.title,
    required this.returnTo,
    required this.child,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    return auth.when(
      data: (session) => session == null
          ? _SignInRequired(title: title, returnTo: returnTo)
          : child,
      loading: () => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: const Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => _SignInRequired(
        title: title,
        returnTo: returnTo,
        message: 'Could not restore your session. Please sign in again.',
      ),
    );
  }
}

class _SignInRequired extends StatelessWidget {
  final String title;
  final String returnTo;
  final String message;

  const _SignInRequired({
    required this.title,
    required this.returnTo,
    this.message = 'Sign in to view your private paper-trading data.',
  });

  @override
  Widget build(BuildContext context) {
    final encoded = Uri.encodeQueryComponent(returnTo);
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 64,
                height: 64,
                decoration: BoxDecoration(
                  color: AppTheme.accentDim,
                  borderRadius: BorderRadius.circular(18),
                ),
                child: Icon(
                  Icons.lock_outline,
                  color: AppTheme.accentDeep,
                  size: 30,
                ),
              ),
              const SizedBox(height: 18),
              Text(
                'Sign in required',
                style: TextStyle(
                  color: AppTheme.ink,
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                message,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AppTheme.inkMuted,
                  fontSize: 14,
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 22),
              ElevatedButton.icon(
                onPressed: () => context.push('/auth?from=$encoded'),
                icon: const Icon(Icons.login, size: 18),
                label: const Text('Sign in or create account'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
