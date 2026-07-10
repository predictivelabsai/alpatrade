import 'package:flutter/material.dart';
import 'package:alpatrade/config/constants.dart';
import 'package:alpatrade/config/theme.dart';

class WelcomeMessage extends StatelessWidget {
  final ValueChanged<String> onPromptTap;

  const WelcomeMessage({super.key, required this.onPromptTap});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                color: AppTheme.accent,
                borderRadius: BorderRadius.circular(20),
              ),
              child: const Center(
                child: Icon(
                  Icons.candlestick_chart,
                  color: Colors.white,
                  size: 36,
                ),
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              'AlpaTrade',
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.w700,
                letterSpacing: -0.5,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'AI Trading Assistant',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: AppTheme.accent,
                letterSpacing: 0.2,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Ask about your paper positions, P&L, market news and movers, '
              'run backtests, or place a paper trade — in plain English or by voice.',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 15,
                color: AppTheme.inkMuted,
                height: 1.5,
              ),
            ),
            const SizedBox(height: 28),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                'Try asking',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.inkDim,
                ),
              ),
            ),
            const SizedBox(height: 10),
            ...AppConstants.samplePrompts
                .take(5)
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
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppTheme.line),
            ),
            child: Row(
              children: [
                Icon(Icons.bolt_outlined, size: 16, color: AppTheme.accent),
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
                Icon(Icons.arrow_forward_ios, size: 12, color: AppTheme.inkDim),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
