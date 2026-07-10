import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/models/daily_scan.dart';
import 'package:carhero/providers/daily_scan_provider.dart';
import 'package:carhero/screens/chat/widgets/chat_sidebar.dart';

class DailyScanScreen extends ConsumerStatefulWidget {
  const DailyScanScreen({super.key});

  @override
  ConsumerState<DailyScanScreen> createState() => _DailyScanScreenState();
}

class _DailyScanScreenState extends ConsumerState<DailyScanScreen> {
  final _searchController = TextEditingController();
  String _searchQuery = '';
  String? _filterMake;
  String? _filterYear;
  double _minGap = 0;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scanAsync = ref.watch(dailyScanProvider);

    return Scaffold(
      drawer: const ChatSidebar(),
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        title: const Text('Daily Scan'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(dailyScanProvider),
          ),
        ],
      ),
      body: scanAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.error_outline, size: 48, color: AppTheme.gray400),
              const SizedBox(height: 12),
              Text(
                'Failed to load scan data',
                style: TextStyle(color: AppTheme.gray500, fontSize: 14),
              ),
              const SizedBox(height: 12),
              ElevatedButton(
                onPressed: () => ref.invalidate(dailyScanProvider),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
        data: (data) => _buildContent(data),
      ),
    );
  }

  Widget _buildContent(DailyScanData data) {
    final comparisons = _filterComparisons(data.comparisons);

    return RefreshIndicator(
      onRefresh: () async => ref.invalidate(dailyScanProvider),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _StatsBanner(stats: data.stats),
          const SizedBox(height: 16),
          _FilterBar(
            comparisons: data.comparisons,
            searchController: _searchController,
            filterMake: _filterMake,
            filterYear: _filterYear,
            minGap: _minGap,
            onSearchChanged: (v) => setState(() => _searchQuery = v),
            onMakeChanged: (v) => setState(() => _filterMake = v),
            onYearChanged: (v) => setState(() => _filterYear = v),
            onGapChanged: (v) => setState(() => _minGap = v),
            onClear: () {
              _searchController.clear();
              setState(() {
                _searchQuery = '';
                _filterMake = null;
                _filterYear = null;
                _minGap = 0;
              });
            },
          ),
          const SizedBox(height: 16),
          Text(
            '${comparisons.length} of ${data.comparisons.length} results',
            style: TextStyle(fontSize: 12, color: AppTheme.gray400),
          ),
          const SizedBox(height: 8),
          Text(
            'Best Price Arbitrage',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: AppTheme.ink,
            ),
          ),
          const SizedBox(height: 8),
          if (comparisons.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Center(
                child: Text(
                  'No matches found.',
                  style: TextStyle(color: AppTheme.gray400, fontSize: 14),
                ),
              ),
            )
          else
            ...comparisons.map((c) => _ComparisonCard(comparison: c)),
          if (data.priceDrops.isNotEmpty) ...[
            const SizedBox(height: 24),
            Text(
              'Price Drops',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: AppTheme.ink,
              ),
            ),
            const SizedBox(height: 8),
            ...data.priceDrops.map((d) => _PriceDropCard(drop: d)),
          ],
        ],
      ),
    );
  }

  List<PriceComparison> _filterComparisons(List<PriceComparison> all) {
    return all.where((c) {
      if (_filterMake != null && c.make != _filterMake) return false;
      if (_filterYear != null && c.year.toString() != _filterYear) return false;
      if (_minGap > 0 && c.savingsEur < _minGap) return false;
      if (_searchQuery.isNotEmpty) {
        final hay = '${c.make} ${c.model} ${c.year}'.toLowerCase();
        if (!hay.contains(_searchQuery.toLowerCase())) return false;
      }
      return true;
    }).toList()..sort((a, b) => b.savingsEur.compareTo(a.savingsEur));
  }
}

class _StatsBanner extends StatelessWidget {
  final DailyScanStats stats;
  const _StatsBanner({required this.stats});

  @override
  Widget build(BuildContext context) {
    if (stats.freshCount == 0 && stats.totalActive == 0) {
      return const SizedBox.shrink();
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFFF0FDF4),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFBBF7D0)),
      ),
      child: Wrap(
        spacing: 6,
        runSpacing: 4,
        alignment: WrapAlignment.center,
        children: [
          _statChip('${_fmt(stats.freshCount)} listings'),
          _dot(),
          _statChip('${_fmt(stats.newCount)} new'),
          _dot(),
          _statChip('${stats.providersScraped} providers'),
          _dot(),
          _statChip('${stats.countriesCovered} countries'),
          if (stats.lastScrape != null) ...[
            _dot(),
            Text(
              'Last scan: ${stats.lastScrape}',
              style: const TextStyle(fontSize: 12, color: Color(0xFF15803D)),
            ),
          ],
        ],
      ),
    );
  }

  Widget _statChip(String text) => Text(
    text,
    style: const TextStyle(
      fontSize: 12,
      fontWeight: FontWeight.w600,
      color: Color(0xFF15803D),
    ),
  );

  Widget _dot() => const Text(
    ' · ',
    style: TextStyle(color: Color(0xFF15803D), fontSize: 12),
  );

  String _fmt(int n) => n.toString().replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+$)'),
    (m) => '${m[1]},',
  );
}

class _FilterBar extends StatelessWidget {
  final List<PriceComparison> comparisons;
  final TextEditingController searchController;
  final String? filterMake;
  final String? filterYear;
  final double minGap;
  final ValueChanged<String> onSearchChanged;
  final ValueChanged<String?> onMakeChanged;
  final ValueChanged<String?> onYearChanged;
  final ValueChanged<double> onGapChanged;
  final VoidCallback onClear;

  const _FilterBar({
    required this.comparisons,
    required this.searchController,
    required this.filterMake,
    required this.filterYear,
    required this.minGap,
    required this.onSearchChanged,
    required this.onMakeChanged,
    required this.onYearChanged,
    required this.onGapChanged,
    required this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    final makes = comparisons.map((c) => c.make).toSet().toList()..sort();
    final years = comparisons.map((c) => c.year.toString()).toSet().toList()
      ..sort((a, b) => b.compareTo(a));

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: AppTheme.gray200),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        children: [
          TextField(
            controller: searchController,
            decoration: const InputDecoration(
              hintText: 'Search make or model...',
              isDense: true,
              prefixIcon: Icon(Icons.search, size: 20),
            ),
            onChanged: onSearchChanged,
            textInputAction: TextInputAction.search,
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: filterMake,
                  decoration: const InputDecoration(
                    hintText: 'All makes',
                    isDense: true,
                    contentPadding: EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 8,
                    ),
                  ),
                  items: [
                    const DropdownMenuItem(
                      value: null,
                      child: Text('All makes'),
                    ),
                    ...makes.map(
                      (m) => DropdownMenuItem(value: m, child: Text(m)),
                    ),
                  ],
                  onChanged: onMakeChanged,
                  isExpanded: true,
                  style: TextStyle(fontSize: 13, color: AppTheme.ink),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: filterYear,
                  decoration: const InputDecoration(
                    hintText: 'All years',
                    isDense: true,
                    contentPadding: EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 8,
                    ),
                  ),
                  items: [
                    const DropdownMenuItem(
                      value: null,
                      child: Text('All years'),
                    ),
                    ...years.map(
                      (y) => DropdownMenuItem(value: y, child: Text(y)),
                    ),
                  ],
                  onChanged: onYearChanged,
                  isExpanded: true,
                  style: TextStyle(fontSize: 13, color: AppTheme.ink),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<double>(
                  value: minGap,
                  decoration: const InputDecoration(
                    isDense: true,
                    contentPadding: EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 8,
                    ),
                  ),
                  items: const [
                    DropdownMenuItem(value: 0, child: Text('Any price gap')),
                    DropdownMenuItem(value: 1000, child: Text('≥ €1,000')),
                    DropdownMenuItem(value: 5000, child: Text('≥ €5,000')),
                    DropdownMenuItem(value: 10000, child: Text('≥ €10,000')),
                    DropdownMenuItem(value: 25000, child: Text('≥ €25,000')),
                    DropdownMenuItem(value: 50000, child: Text('≥ €50,000')),
                  ],
                  onChanged: (v) => onGapChanged(v ?? 0),
                  isExpanded: true,
                  style: TextStyle(fontSize: 13, color: AppTheme.ink),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton(onPressed: onClear, child: const Text('Clear')),
            ],
          ),
        ],
      ),
    );
  }
}

class _ComparisonCard extends StatelessWidget {
  final PriceComparison comparison;
  const _ComparisonCard({required this.comparison});

  @override
  Widget build(BuildContext context) {
    final c = comparison;
    final pct = c.savingsPct;
    final badgeColor = pct >= 15
        ? AppTheme.green600
        : (pct >= 8 ? const Color(0xFFF59E0B) : AppTheme.gray500);

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: AppTheme.gray200),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 6,
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${c.make} ${c.model}',
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 14,
                    ),
                  ),
                  Text(
                    '${c.year}',
                    style: TextStyle(fontSize: 13, color: AppTheme.gray500),
                  ),
                  Text(
                    '${c.listingCount} listings · ${c.sourceCount} sources',
                    style: TextStyle(fontSize: 11, color: AppTheme.gray400),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 4,
                ),
                decoration: BoxDecoration(
                  color: badgeColor,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  'Save ${_eur(c.savingsEur)} (${pct.toStringAsFixed(0)}%)',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          LayoutBuilder(
            builder: (context, constraints) {
              final boxes = [
                _PriceBox(
                  label: 'CHEAPEST',
                  price: c.cheapPrice,
                  source: '${c.cheapCountry ?? ''} / ${c.cheapProvider ?? ''}',
                  km: c.cheapKm,
                  url: c.cheapUrl,
                  bgColor: const Color(0xFFF0FDF4),
                  labelColor: AppTheme.green600,
                  priceColor: const Color(0xFF15803D),
                ),
                _PriceBox(
                  label: 'MOST EXPENSIVE',
                  price: c.expensivePrice,
                  source:
                      '${c.expensiveCountry ?? ''} / ${c.expensiveProvider ?? ''}',
                  url: c.expensiveUrl,
                  bgColor: const Color(0xFFFEF2F2),
                  labelColor: AppTheme.red600,
                  priceColor: const Color(0xFF991B1B),
                ),
              ];
              if (constraints.maxWidth < 300) {
                return Column(
                  children: [boxes[0], const SizedBox(height: 6), boxes[1]],
                );
              }
              return Row(
                children: [
                  Expanded(child: boxes[0]),
                  const SizedBox(width: 8),
                  Expanded(child: boxes[1]),
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  String _eur(double n) =>
      '€${n.toStringAsFixed(0).replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},')}';
}

class _PriceBox extends StatelessWidget {
  final String label;
  final double price;
  final String source;
  final int? km;
  final String? url;
  final Color bgColor;
  final Color labelColor;
  final Color priceColor;

  const _PriceBox({
    required this.label,
    required this.price,
    required this.source,
    this.km,
    this.url,
    required this.bgColor,
    required this.labelColor,
    required this.priceColor,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w600,
              color: labelColor,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            _eur(price),
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: priceColor,
            ),
          ),
          Text(
            source + (km != null ? ' · ${_fmtKm(km!)} km' : ''),
            style: TextStyle(fontSize: 11, color: AppTheme.gray500),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          if (url != null && url!.isNotEmpty)
            GestureDetector(
              onTap: () => launchUrl(
                Uri.parse(url!),
                mode: LaunchMode.externalApplication,
              ),
              child: Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'View listing',
                  style: TextStyle(
                    fontSize: 11,
                    color: AppTheme.ink,
                    decoration: TextDecoration.underline,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  String _eur(double n) =>
      '€${n.toStringAsFixed(0).replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},')}';

  String _fmtKm(int n) => n.toString().replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+$)'),
    (m) => '${m[1]},',
  );
}

class _PriceDropCard extends StatelessWidget {
  final PriceDrop drop;
  const _PriceDropCard({required this.drop});

  @override
  Widget build(BuildContext context) {
    final d = drop;
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        border: Border.all(color: AppTheme.gray200),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${d.make} ${d.model} ${d.variant ?? ''}'.trim(),
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  [
                    if (d.year > 0) '${d.year}',
                    if (d.mileageKm != null) '${_fmtKm(d.mileageKm!)} km',
                    '${d.country ?? ''} / ${d.provider ?? ''}',
                  ].join(' · '),
                  style: TextStyle(fontSize: 12, color: AppTheme.gray500),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          const SizedBox(width: 16),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                _eur(d.priceEur),
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  fontSize: 14,
                ),
              ),
              const SizedBox(height: 2),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    _eur(d.oldPrice),
                    style: TextStyle(
                      fontSize: 11,
                      color: AppTheme.gray400,
                      decoration: TextDecoration.lineThrough,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    '↓${d.dropPct.toStringAsFixed(0)}%',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.green600,
                    ),
                  ),
                ],
              ),
              if (d.sourceUrl != null && d.sourceUrl!.isNotEmpty)
                GestureDetector(
                  onTap: () => launchUrl(
                    Uri.parse(d.sourceUrl!),
                    mode: LaunchMode.externalApplication,
                  ),
                  child: Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      'View listing',
                      style: TextStyle(
                        fontSize: 11,
                        color: AppTheme.ink,
                        decoration: TextDecoration.underline,
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  String _eur(double n) =>
      '€${n.toStringAsFixed(0).replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},')}';

  String _fmtKm(int n) => n.toString().replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+$)'),
    (m) => '${m[1]},',
  );
}
