import 'dart:async';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:alpatrade/providers/api_provider.dart';
import 'package:alpatrade/providers/auth_provider.dart';
import 'package:alpatrade/services/research_service.dart';
import 'package:alpatrade/screens/chat/widgets/responsive_markdown.dart';

final researchServiceProvider = Provider(
  (ref) => ResearchService(ref.watch(apiClientProvider)),
);
final researchDataProvider = FutureProvider.autoDispose
    .family<
      Map<String, dynamic>,
      ({
        String section,
        String query,
        String filter,
        String holds,
        String period,
        String aum,
        String sort,
      })
    >((ref, args) {
      final service = ref.watch(researchServiceProvider);
      return switch (args.section) {
        'leaderboard' => service.leaderboard(
          query: args.query,
          kind: args.filter,
        ),
        'strategies' => service.strategies(),
        'funds' => service.funds(
          query: args.query,
          holds: args.holds,
          period: args.period,
          minAum: args.aum,
          sort: args.sort,
        ),
        'performance' => service.performance(
          args.filter.isEmpty ? 'quarter_end' : args.filter,
        ),
        'activists' => service.activists(args.query),
        'ipos' => service.ipos(pipeline: args.filter == 'pipeline'),
        _ => service.advisor().then((rows) => {'reports': rows}),
      };
    });

String researchPercent(dynamic value) =>
    value is num ? '${value.toStringAsFixed(2)}%' : '—';
String _money(dynamic value) => value is num
    ? NumberFormat.compactCurrency(symbol: '\$').format(value)
    : '—';

class ResearchScreen extends ConsumerStatefulWidget {
  final String section;
  final String title;
  const ResearchScreen({super.key, required this.section, required this.title});
  @override
  ConsumerState<ResearchScreen> createState() => _ResearchScreenState();
}

class _ResearchScreenState extends ConsumerState<ResearchScreen> {
  String query = '',
      filter = '',
      holds = '',
      period = '',
      aum = '',
      sort = 'aum';
  @override
  Widget build(BuildContext context) {
    final section = widget.section;
    final provider = researchDataProvider((
      section: section,
      query: query,
      filter: filter,
      holds: holds,
      period: period,
      aum: aum,
      sort: sort,
    ));
    final data = ref.watch(provider);
    final choices = switch (section) {
      'leaderboard' => {'': 'All', 'live': 'Live', 'backtest': 'Backtests'},
      'performance' => {'': 'Quarter end', 'follow_filing': 'Follow filing'},
      'ipos' => {'': 'Listed', 'pipeline': 'Pipeline'},
      _ => <String, String>{},
    };
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          if (section == 'leaderboard')
            IconButton(
              tooltip: 'My strategies',
              icon: const Icon(Icons.bookmarks_outlined),
              onPressed: () => context.push('/more/my-strategies'),
            ),
        ],
      ),
      body: Column(
        children: [
          if (['leaderboard', 'funds', 'activists'].contains(section))
            Padding(
              padding: const EdgeInsets.all(12),
              child: TextField(
                decoration: InputDecoration(
                  labelText: section == 'activists'
                      ? 'Ticker'
                      : 'Search ${widget.title.toLowerCase()}',
                  suffixIcon: const Icon(Icons.search),
                ),
                textInputAction: TextInputAction.search,
                onSubmitted: (value) => setState(() => query = value.trim()),
              ),
            ),
          if (choices.isNotEmpty)
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final e in choices.entries)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: ChoiceChip(
                        label: Text(e.value),
                        selected: filter == e.key,
                        onSelected: (_) => setState(() => filter = e.key),
                      ),
                    ),
                ],
              ),
            ),
          if (section == 'funds')
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: ExpansionTile(
                title: const Text('Screener filters'),
                children: [
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Holds ticker (e.g. AAPL)',
                    ),
                    onSubmitted: (v) =>
                        setState(() => holds = v.trim().toUpperCase()),
                  ),
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Filing period (YYYY-MM-DD; blank = latest)',
                    ),
                    onSubmitted: (v) => setState(() => period = v.trim()),
                  ),
                  DropdownButton<String>(
                    value: aum,
                    isExpanded: true,
                    items: [
                      for (final e in {
                        '': 'Any portfolio size',
                        '100m': '\$100M+',
                        '1b': '\$1B+',
                        '10b': '\$10B+',
                        '100b': '\$100B+',
                      }.entries)
                        DropdownMenuItem(value: e.key, child: Text(e.value)),
                    ],
                    onChanged: (v) => setState(() => aum = v!),
                  ),
                  DropdownButton<String>(
                    value: sort,
                    isExpanded: true,
                    items: [
                      for (final e in {
                        'aum': 'Portfolio size',
                        'positions': 'Positions',
                        'name': 'Name',
                        'filed': 'Filing date',
                        'ttm': 'TTM return',
                      }.entries)
                        DropdownMenuItem(
                          value: e.key,
                          child: Text('Sort: ${e.value}'),
                        ),
                    ],
                    onChanged: (v) => setState(() => sort = v!),
                  ),
                ],
              ),
            ),
          if (section == 'performance')
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text(
                'Estimated from delayed 13F holdings; not reported fund performance.',
              ),
            ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async {
                ref.invalidate(provider);
                await ref.read(provider.future);
              },
              child: data.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (error, _) => ListView(
                  children: [
                    const SizedBox(height: 60),
                    const Center(child: Text('Could not load research.')),
                    Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(
                        '$error',
                        maxLines: 4,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    Center(
                      child: FilledButton(
                        onPressed: () => ref.invalidate(provider),
                        child: const Text('Retry'),
                      ),
                    ),
                  ],
                ),
                data: (result) {
                  final rows =
                      (result['strategies'] ??
                              result['rows'] ??
                              result['funds'] ??
                              result['filings'] ??
                              result['ipos'] ??
                              result['reports'] ??
                              [])
                          as List;
                  return ListView(
                    padding: const EdgeInsets.all(12),
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      if (result['period'] != null)
                        Text('Filing period: ${result['period']}'),
                      if (result['computed_at'] != null)
                        Text('Updated: ${result['computed_at']}'),
                      if (rows.isEmpty)
                        Padding(
                          padding: const EdgeInsets.all(32),
                          child: Text(
                            result['holds_unmapped'] == true
                                ? 'No holdings mapping for this ticker.'
                                : 'No results available.',
                          ),
                        ),
                      for (final raw in rows)
                        _card(Map<String, dynamic>.from(raw)),
                    ],
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _card(Map<String, dynamic> row) {
    final section = widget.section;
    final strategy = section == 'leaderboard' || section == 'strategies';
    final m = row['metrics'] as Map? ?? {};
    final title =
        row['name'] ??
        row['company'] ??
        row['subject'] ??
        row['headline'] ??
        'Research';
    final lines = <String>[
      if (strategy)
        '${row['author'] ?? ''} · ${row['kind'] == 'backtest' ? 'Hypothetical backtest' : 'Live strategy'}',
      if (strategy)
        'Return ${researchPercent(m['return_pct'])} · Annualised ${researchPercent(m['annualised_pct'])}',
      if (strategy)
        'As of ${m['as_of'] ?? '—'} · ${m['trading_days'] ?? '—'} trading days',
      if (section == 'funds' || section == 'performance')
        '13F portfolio ${_money(row['value'])} · ${row['positions'] ?? '—'} positions',
      if (section == 'funds')
        'Filed ${row['filed'] ?? '—'} · ${row['form'] ?? ''}',
      if (section == 'performance')
        'Period ${row['latest_period'] ?? '—'} · Filed ${row['latest_filed'] ?? '—'}',
      if (section == 'performance')
        for (final e in (row['returns'] as Map? ?? {}).entries)
          '${e.key}: ${researchPercent(e.value['fund'] is num ? e.value['fund'] * 100 : null)} · SPY ${researchPercent(e.value['spy'] is num ? e.value['spy'] * 100 : null)}',
      if (section == 'activists')
        '${row['ticker'] ?? ''} · ${row['form'] ?? ''} · ${row['date'] ?? ''}\n${row['filer'] ?? ''}',
      if (section == 'ipos')
        '${row['ticker'] ?? ''} · ${row['ipo_date'] ?? row['status'] ?? ''}\nIPO ${_money(row['ipo_price'])} · Return ${researchPercent(row['return_pct'])}',
      if (section == 'advisor')
        '${row['session_date']} · ${row['severity']}\n${row['summary'] ?? ''}',
    ];
    return Card(
      child: ListTile(
        isThreeLine: true,
        title: Text('${row['rank'] == null ? '' : '#${row['rank']} '}$title'),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(lines.join('\n')),
        ),
        trailing: strategy ? const Icon(Icons.chevron_right) : null,
        onTap: strategy
            ? () => context.push('/more/leaderboard/${row['id']}')
            : section == 'advisor'
            ? () => showModalBottomSheet(
                context: context,
                isScrollControlled: true,
                builder: (_) => SafeArea(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(20),
                    child: Text(
                      [
                        row['summary'] ?? '',
                        for (final item in row['recommendations'] ?? [])
                          '${item['title']}\n${item['rationale']}\n${item['explanation'] ?? ''}',
                        row['why_no_change'] ?? '',
                        ...(row['data_warnings'] as List? ?? []),
                        row['disclaimer'] ?? '',
                      ].join('\n\n'),
                    ),
                  ),
                ),
              )
            : section == 'activists' && row['url'] != null
            ? () {
                final uri = Uri.tryParse(row['url']);
                if (uri != null && ['http', 'https'].contains(uri.scheme)) {
                  launchUrl(uri, mode: LaunchMode.externalApplication);
                }
              }
            : null,
      ),
    );
  }
}

final strategyDetailProvider = FutureProvider.autoDispose
    .family<Map<String, dynamic>, int>(
      (ref, id) => ref.watch(researchServiceProvider).strategy(id),
    );

class ResearchStrategyScreen extends ConsumerStatefulWidget {
  final int id;
  const ResearchStrategyScreen({super.key, required this.id});
  @override
  ConsumerState<ResearchStrategyScreen> createState() =>
      _ResearchStrategyScreenState();
}

class _ResearchStrategyScreenState
    extends ConsumerState<ResearchStrategyScreen> {
  bool cloning = false;
  Timer? poll;
  String? jobMessage;
  String? jobMarkdown;
  bool running = false;
  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  Future<void> runBacktest() async {
    setState(() {
      running = true;
      jobMessage = 'Starting backtest…';
      jobMarkdown = null;
    });
    try {
      final service = ref.read(researchServiceProvider);
      final job = await service.backtest(widget.id);
      Future<void> check() async {
        try {
          final status = await service.backtestStatus(job['job_id']);
          if (!mounted) return;
          setState(() {
            jobMessage = status['message'];
            jobMarkdown = status['markdown'];
            running = status['state'] == 'running';
          });
          if (running) {
            poll = Timer(const Duration(seconds: 3), check);
          } else {
            ref.invalidate(strategyDetailProvider(widget.id));
          }
        } catch (_) {
          if (mounted) {
            setState(() {
              running = false;
              jobMessage =
                  'Could not check backtest. Reopen the strategy to see saved results.';
            });
          }
        }
      }

      await check();
    } catch (_) {
      if (mounted) {
        setState(() {
          running = false;
          jobMessage = 'Could not start backtest. Please retry.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = strategyDetailProvider(widget.id);
    return Scaffold(
      appBar: AppBar(title: const Text('Strategy detail')),
      body: ref
          .watch(provider)
          .when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => Center(
              child: FilledButton(
                onPressed: () => ref.invalidate(provider),
                child: const Text('Retry loading strategy'),
              ),
            ),
            data: (s) => ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(
                  s['name'] ?? '',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                Text(
                  '${s['author'] ?? ''} · ${s['kind'] == 'backtest' ? 'Hypothetical backtest' : 'Live strategy'}',
                ),
                const SizedBox(height: 16),
                Text(s['description'] ?? ''),
                const SizedBox(height: 16),
                Text(s['methodology'] ?? ''),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: cloning
                      ? null
                      : () async {
                          final session = ref
                              .read(authProvider)
                              .whenOrNull(data: (value) => value);
                          if (session == null) {
                            context.push(
                              '/auth?from=${Uri.encodeComponent('/more/leaderboard/${widget.id}')}',
                            );
                            return;
                          }
                          setState(() => cloning = true);
                          try {
                            final result = await ref
                                .read(researchServiceProvider)
                                .clone(widget.id);
                            if (!context.mounted) return;
                            context.push('/more/leaderboard/${result['id']}');
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text(
                                  'Private strategy ready in My strategies.',
                                ),
                              ),
                            );
                          } catch (e) {
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(
                                    'Could not clone. Sign in and retry. $e',
                                  ),
                                ),
                              );
                            }
                          } finally {
                            if (mounted) setState(() => cloning = false);
                          }
                        },
                  icon: const Icon(Icons.copy),
                  label: Text(cloning ? 'Cloning…' : 'Clone to my strategies'),
                ),
                const SizedBox(height: 16),
                if (s['is_owner'] == true)
                  OutlinedButton.icon(
                    onPressed: running ? null : runBacktest,
                    icon: const Icon(Icons.science_outlined),
                    label: const Text('Run hypothetical backtest'),
                  ),
                if (jobMessage != null) Text(jobMessage!),
                if (jobMarkdown != null) ResponsiveMarkdown(data: jobMarkdown!),
                ResponsiveMarkdown(data: s['skill_md'] ?? ''),
              ],
            ),
          ),
    );
  }
}
