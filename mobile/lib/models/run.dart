/// One strategy run — mirrors RunItem in the AlpaTrade v2 API.
class Run {
  final String runId;
  final String mode; // 'paper' | 'backtest'
  final String? strategy;
  final String? strategySlug;
  final String status;
  final String? startedAt;
  final String? completedAt;

  const Run({
    required this.runId,
    required this.mode,
    this.strategy,
    this.strategySlug,
    required this.status,
    this.startedAt,
    this.completedAt,
  });

  factory Run.fromJson(Map<String, dynamic> j) => Run(
    runId: j['run_id'] as String? ?? '',
    mode: j['mode'] as String? ?? 'paper',
    strategy: j['strategy'] as String?,
    strategySlug: j['strategy_slug'] as String?,
    status: j['status'] as String? ?? '',
    startedAt: j['started_at'] as String?,
    completedAt: j['completed_at'] as String?,
  );
}

/// Response envelope for GET /v2/runs.
class RunsResponse {
  final List<Run> runs;
  final int total;

  const RunsResponse({required this.runs, required this.total});

  factory RunsResponse.fromJson(Map<String, dynamic> j) => RunsResponse(
    runs: ((j['runs'] as List?) ?? [])
        .map((e) => Run.fromJson(e as Map<String, dynamic>))
        .toList(),
    total: (j['total'] as num?)?.toInt() ?? 0,
  );
}
