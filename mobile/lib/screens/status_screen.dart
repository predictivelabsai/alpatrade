import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/providers/market_provider.dart';
import 'package:alpatrade/utils/formatters.dart';
import 'package:alpatrade/widgets/error_view.dart';

class StatusScreen extends ConsumerWidget {
  const StatusScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(statusProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Agent status')),
      body: RefreshIndicator(
        onRefresh: () => ref.refresh(statusProvider.future),
        color: AppTheme.accent,
        child: async.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(
            children: [
              const SizedBox(height: 120),
              ErrorView(
                title: 'Could not load status',
                message: '$e',
                onRetry: () => ref.invalidate(statusProvider),
              ),
            ],
          ),
          data: (data) {
            final status = (data['status'] ?? 'unknown').toString();
            final runId = data['run_id']?.toString();
            final mode = data['mode']?.toString();
            final startedAt = data['started_at']?.toString();
            final elapsed = data['elapsed_seconds'];
            final agents = (data['agents'] as List<dynamic>?) ?? const [];

            return ListView(
              padding: const EdgeInsets.fromLTRB(12, 16, 12, 24),
              children: [
                _RunCard(
                  status: status,
                  runId: runId,
                  mode: mode,
                  startedAt: startedAt,
                  elapsedSeconds: elapsed is num ? elapsed : null,
                ),
                if (agents.isNotEmpty) ...[
                  const SizedBox(height: 20),
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 4,
                      vertical: 8,
                    ),
                    child: Text(
                      'Agents (${agents.length})',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.inkDim,
                      ),
                    ),
                  ),
                  ...agents.whereType<Map<String, dynamic>>().map(
                    (a) => _AgentTile(agent: a),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

Color _statusColor(String status) {
  switch (status.toLowerCase()) {
    case 'completed':
    case 'complete':
    case 'done':
    case 'success':
      return AppTheme.gain;
    case 'running':
    case 'in_progress':
    case 'started':
      return AppTheme.accent;
    case 'failed':
    case 'error':
      return AppTheme.loss;
    default:
      return AppTheme.inkDim;
  }
}

class _StatusChip extends StatelessWidget {
  final String status;
  const _StatusChip({required this.status});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(
        status.toUpperCase(),
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: color,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}

class _RunCard extends StatelessWidget {
  final String status;
  final String? runId;
  final String? mode;
  final String? startedAt;
  final num? elapsedSeconds;

  const _RunCard({
    required this.status,
    required this.runId,
    required this.mode,
    required this.startedAt,
    required this.elapsedSeconds,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                'Run status',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.inkDim,
                ),
              ),
              const Spacer(),
              _StatusChip(status: status),
            ],
          ),
          const SizedBox(height: 14),
          if (runId != null && runId!.isNotEmpty)
            _InfoRow(label: 'Run ID', value: runId!, mono: true),
          if (mode != null && mode!.isNotEmpty)
            _InfoRow(label: 'Mode', value: mode!),
          if (startedAt != null && startedAt!.isNotEmpty)
            _InfoRow(label: 'Started', value: Fmt.dateTimeShort(startedAt)),
          if (elapsedSeconds != null)
            _InfoRow(
              label: 'Elapsed',
              value: '${elapsedSeconds!.round()}s',
              mono: true,
            ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  final bool mono;

  const _InfoRow({required this.label, required this.value, this.mono = false});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80,
            child: Text(
              label,
              style: TextStyle(fontSize: 13, color: AppTheme.inkDim),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                fontSize: 13,
                color: AppTheme.ink,
                fontWeight: FontWeight.w500,
                fontFamily: mono ? AppTheme.monoFont : null,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AgentTile extends StatelessWidget {
  final Map<String, dynamic> agent;
  const _AgentTile({required this.agent});

  @override
  Widget build(BuildContext context) {
    final name = (agent['name'] ?? '—').toString();
    final status = (agent['status'] ?? 'unknown').toString();
    final task = agent['current_task']?.toString();

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  name,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.ink,
                  ),
                ),
              ),
              _StatusChip(status: status),
            ],
          ),
          if (task != null && task.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              task,
              style: TextStyle(
                fontSize: 12,
                color: AppTheme.inkDim,
                height: 1.4,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
