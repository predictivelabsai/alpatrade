import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/providers/agent_provider.dart';

class WelcomeMessage extends ConsumerWidget {
  final ValueChanged<String> onPromptTap;

  const WelcomeMessage({super.key, required this.onPromptTap});

  static const _fallbackPrompts = [
    "What's the best Porsche I can get for 100k?",
    'Any sleeper deals on GT cars right now?',
    "I've got 50k and want something that turns heads",
    'What should I be buying before prices go up?',
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final agentsAsync = ref.watch(agentsProvider);

    // Feature Kenri — surface its example prompts when available.
    final prompts =
        agentsAsync.whenOrNull(
          data: (agents) {
            final kenriMatches = agents.where((a) => a.slug == 'kenri');
            final featured = kenriMatches.isNotEmpty
                ? kenriMatches.first
                : (agents.isNotEmpty ? agents.first : null);
            return featured != null && featured.examplePrompts.isNotEmpty
                ? featured.examplePrompts
                : _fallbackPrompts;
          },
        ) ??
        _fallbackPrompts;

    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Logo / icon area
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                color: AppTheme.ink,
                borderRadius: BorderRadius.circular(20),
              ),
              child: const Center(
                child: Text(
                  'K',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 28,
                    fontWeight: FontWeight.w700,
                    letterSpacing: -1,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Title
            const Text(
              'Kenri.ai',
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.w700,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Personal Advisor',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: AppTheme.gray500,
                letterSpacing: 0.2,
              ),
            ),
            const SizedBox(height: 8),

            // Subtitle
            Text(
              'Your personal car advisor — finds the deals, drops the knowledge, and pushes you toward the best buys across 150,000+ European listings.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 15,
                color: AppTheme.gray500,
                height: 1.5,
              ),
            ),
            const SizedBox(height: 32),

            // Example prompts header
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                'Try asking',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.gray500,
                ),
              ),
            ),
            const SizedBox(height: 10),

            // Prompt chips
            ...prompts
                .take(4)
                .map(
                  (prompt) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _PromptChip(
                      text: prompt,
                      onTap: () => onPromptTap(prompt),
                    ),
                  ),
                ),
          ],
        ),
      ),
    );
  }
}

class _PromptChip extends StatelessWidget {
  final String text;
  final VoidCallback onTap;

  const _PromptChip({required this.text, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppTheme.gray200),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.auto_awesome_outlined,
                  size: 16,
                  color: AppTheme.gray400,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    text,
                    style: TextStyle(
                      fontSize: 13,
                      color: AppTheme.ink,
                      height: 1.3,
                    ),
                  ),
                ),
                Icon(
                  Icons.arrow_forward_ios,
                  size: 12,
                  color: AppTheme.gray400,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
