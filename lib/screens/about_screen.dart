import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'package:carhero/config/theme.dart';

class AboutScreen extends StatelessWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (Navigator.of(context).canPop()) {
              Navigator.of(context).pop();
            } else {
              context.go('/');
            }
          },
        ),
        title: const Text('About'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Logo & title
            Center(
              child: Column(
                children: [
                  Container(
                    width: 72,
                    height: 72,
                    decoration: BoxDecoration(
                      color: AppTheme.ink,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    alignment: Alignment.center,
                    child: const Text(
                      'K',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 28,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -1,
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'Kenri.ai',
                    style: TextStyle(
                      fontSize: 32,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.ink,
                      letterSpacing: -0.5,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Your Personal Advisor',
                    style: TextStyle(fontSize: 15, color: AppTheme.gray500),
                  ),
                ],
              ),
            ),

            const SizedBox(height: 40),

            // Mission
            _sectionTitle('Our Mission'),
            const SizedBox(height: 12),
            Text(
              'Kenri.ai helps car buyers make smarter decisions. We combine real-time '
              'market data from multiple European sources with advanced AI to provide '
              'personalised search, accurate valuations, and expert-level advice -- '
              'all through a simple chat interface.',
              style: _bodyStyle,
            ),
            const SizedBox(height: 12),
            Text(
              'Whether you are looking for a daily driver or a weekend sports car, '
              'Kenri.ai surfaces the best options, flags overpriced listings, and '
              'highlights hidden gems that match your exact preferences.',
              style: _bodyStyle,
            ),

            const SizedBox(height: 32),

            // Technology
            _sectionTitle('Technology'),
            const SizedBox(height: 12),
            Text(
              'Kenri.ai is powered by a multi-agent AI system. Specialised agents '
              'handle search, valuation, market analysis, and advisory tasks '
              'concurrently, orchestrated by a triage agent that routes your '
              'questions to the right expert.',
              style: _bodyStyle,
            ),
            const SizedBox(height: 12),
            Text(
              'Our data pipeline aggregates listings from 8+ sources across 5+ '
              'European countries, normalising prices, specifications, and '
              'condition details into a unified format for fair comparison.',
              style: _bodyStyle,
            ),

            const SizedBox(height: 32),

            // Contact
            _sectionTitle('Get in Touch'),
            const SizedBox(height: 12),
            Text(
              'Have questions, feedback, or partnership inquiries? We would love to hear from you.',
              style: _bodyStyle,
            ),
            const SizedBox(height: 16),
            SizedBox(
              height: 44,
              child: OutlinedButton.icon(
                onPressed: () => context.go('/contact'),
                style: OutlinedButton.styleFrom(
                  side: BorderSide(color: AppTheme.ink),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8),
                  ),
                ),
                icon: const Icon(Icons.mail_outline, size: 18),
                label: const Text('Contact Us'),
              ),
            ),

            const SizedBox(height: 48),

            // Footer
            Center(
              child: Text(
                'Kenri.ai v1.0.0',
                style: TextStyle(fontSize: 12, color: AppTheme.gray400),
              ),
            ),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  Widget _sectionTitle(String text) {
    return Text(
      text,
      style: TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.w700,
        color: AppTheme.ink,
      ),
    );
  }

  static final _bodyStyle = TextStyle(
    fontSize: 14,
    color: AppTheme.gray500,
    height: 1.6,
  );
}
