import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/market_map.dart';
import 'package:carhero/providers/market_map_provider.dart';
import 'package:carhero/utils/formatters.dart';
import 'package:carhero/screens/chat/widgets/chat_sidebar.dart';

class MarketMapScreen extends ConsumerStatefulWidget {
  const MarketMapScreen({super.key});

  @override
  ConsumerState<MarketMapScreen> createState() => _MarketMapScreenState();
}

class _MarketMapScreenState extends ConsumerState<MarketMapScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      drawer: const ChatSidebar(),
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        title: const Text('Market Map'),
        bottom: TabBar(
          controller: _tabController,
          labelColor: AppTheme.ink,
          unselectedLabelColor: AppTheme.gray400,
          indicatorColor: AppTheme.ink,
          tabs: const [
            Tab(text: 'Overview'),
            Tab(text: 'Value Map'),
            Tab(text: 'Price Index'),
          ],
        ),
      ),
      body: Column(
        children: [
          _FilterBar(),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: const [
                _OverviewTab(),
                _ValueMapTab(),
                _PriceIndexTab(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Filter Bar
// ---------------------------------------------------------------------------

class _FilterBar extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final filtersAsync = ref.watch(marketFiltersProvider);
    final selectedCountry = ref.watch(marketCountryFilterProvider);
    final selectedMake = ref.watch(marketMakeFilterProvider);
    final selectedFuel = ref.watch(marketFuelTypeFilterProvider);

    return filtersAsync.when(
      loading: () => const Padding(
        padding: EdgeInsets.all(12),
        child: Center(child: LinearProgressIndicator()),
      ),
      error: (_, __) => const SizedBox.shrink(),
      data: (filters) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: AppTheme.gray200)),
        ),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              _FilterDropdown(
                label: 'Country',
                value: selectedCountry,
                items: filters.countries,
                onChanged: (v) =>
                    ref.read(marketCountryFilterProvider.notifier).set(v),
              ),
              const SizedBox(width: 8),
              _FilterDropdown(
                label: 'Brand',
                value: selectedMake,
                items: filters.makes,
                onChanged: (v) =>
                    ref.read(marketMakeFilterProvider.notifier).set(v),
              ),
              const SizedBox(width: 8),
              _FilterDropdown(
                label: 'Fuel Type',
                value: selectedFuel,
                items: filters.fuelTypes,
                onChanged: (v) =>
                    ref.read(marketFuelTypeFilterProvider.notifier).set(v),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _FilterDropdown extends StatelessWidget {
  final String label;
  final String? value;
  final List<String> items;
  final ValueChanged<String?> onChanged;

  const _FilterDropdown({
    required this.label,
    required this.value,
    required this.items,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      decoration: BoxDecoration(
        border: Border.all(color: AppTheme.gray200),
        borderRadius: BorderRadius.circular(8),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String?>(
          value: value,
          hint: Text(
            label,
            style: TextStyle(fontSize: 13, color: AppTheme.gray500),
          ),
          isDense: true,
          style: TextStyle(fontSize: 13, color: AppTheme.ink),
          items: [
            DropdownMenuItem<String?>(
              value: null,
              child: Text(
                'All $label',
                style: TextStyle(fontSize: 13, color: AppTheme.gray500),
              ),
            ),
            ...items.map(
              (item) => DropdownMenuItem(
                value: item,
                child: Text(item, style: const TextStyle(fontSize: 13)),
              ),
            ),
          ],
          onChanged: onChanged,
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

class _OverviewTab extends ConsumerWidget {
  const _OverviewTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SectionHeading('Market Overview'),
          const SizedBox(height: 8),
          _TreemapChart(),
          const SizedBox(height: 24),

          // Price by Model Year - line chart
          _SectionHeading('Price by Model Year'),
          const SizedBox(height: 8),
          _TrendsLineChart(),
          const SizedBox(height: 24),

          // Geographic Comparison - bar chart
          _SectionHeading('Geographic Comparison'),
          const SizedBox(height: 8),
          _GeoBarChart(),
        ],
      ),
    );
  }
}

class _TreemapChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final treemapAsync = ref.watch(treemapProvider);

    return treemapAsync.when(
      loading: () => _chartLoading(),
      error: (e, _) => _chartError(e),
      data: (items) {
        if (items.isEmpty) return _chartEmpty('No treemap data available');
        return SizedBox(height: 280, child: _TreemapPainter(items: items));
      },
    );
  }
}

class _TreemapPainter extends StatelessWidget {
  final List<TreemapItem> items;

  const _TreemapPainter({required this.items});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final rects = _squarify(
          items,
          Rect.fromLTWH(0, 0, constraints.maxWidth, constraints.maxHeight),
        );

        final prices = items.map((i) => i.avgPrice).toList();
        final minPrice = prices.reduce((a, b) => a < b ? a : b);
        final maxPrice = prices.reduce((a, b) => a > b ? a : b);
        final range = maxPrice - minPrice;

        return ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: Stack(
            children: List.generate(rects.length, (i) {
              final rect = rects[i];
              final item = items[i];
              final t = range > 0 ? (item.avgPrice - minPrice) / range : 0.5;
              final color = Color.lerp(
                const Color(0xFF4CAF50),
                const Color(0xFFF44336),
                t,
              )!;

              return Positioned(
                left: rect.left,
                top: rect.top,
                width: rect.width,
                height: rect.height,
                child: Container(
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.75),
                    border: Border.all(color: Colors.white, width: 1),
                  ),
                  padding: const EdgeInsets.all(4),
                  child: rect.width > 50 && rect.height > 30
                      ? Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              '${item.make} ${item.model}',
                              style: const TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w600,
                                color: Colors.white,
                              ),
                              overflow: TextOverflow.ellipsis,
                              maxLines: 1,
                            ),
                            if (rect.height > 45)
                              Text(
                                '${item.listingCount} listings',
                                style: TextStyle(
                                  fontSize: 9,
                                  color: Colors.white.withValues(alpha: 0.85),
                                ),
                              ),
                            if (rect.height > 60)
                              Text(
                                Fmt.price(item.avgPrice),
                                style: TextStyle(
                                  fontSize: 9,
                                  color: Colors.white.withValues(alpha: 0.85),
                                ),
                              ),
                          ],
                        )
                      : null,
                ),
              );
            }),
          ),
        );
      },
    );
  }

  List<Rect> _squarify(List<TreemapItem> items, Rect bounds) {
    final sorted = List<TreemapItem>.from(items)
      ..sort((a, b) => b.listingCount.compareTo(a.listingCount));

    final totalArea = bounds.width * bounds.height;
    final totalValue = sorted.fold<int>(
      0,
      (sum, item) => sum + item.listingCount,
    );

    if (totalValue == 0) {
      return List.filled(sorted.length, Rect.zero);
    }

    final areas = sorted
        .map((item) => (item.listingCount / totalValue) * totalArea)
        .toList();

    final rects = List<Rect>.filled(sorted.length, Rect.zero);
    _layoutRow(areas, rects, 0, areas.length, bounds);

    final indexMap = <int, int>{};
    for (int i = 0; i < sorted.length; i++) {
      indexMap[items.indexOf(sorted[i])] = i;
    }

    final result = List<Rect>.filled(items.length, Rect.zero);
    for (int i = 0; i < items.length; i++) {
      result[i] = rects[indexMap[i]!];
    }
    return result;
  }

  void _layoutRow(
    List<double> areas,
    List<Rect> rects,
    int start,
    int end,
    Rect bounds,
  ) {
    if (start >= end) return;
    if (end - start == 1) {
      rects[start] = bounds;
      return;
    }

    final total = areas.sublist(start, end).fold<double>(0, (a, b) => a + b);
    final isWide = bounds.width >= bounds.height;

    double rowTotal = 0;
    int split = start;
    final half = total / 2;
    for (int i = start; i < end; i++) {
      if (rowTotal + areas[i] > half && i > start) break;
      rowTotal += areas[i];
      split = i + 1;
    }
    if (split == start) split = start + 1;

    final fraction = total > 0 ? rowTotal / total : 0.5;

    Rect first, second;
    if (isWide) {
      final w = bounds.width * fraction;
      first = Rect.fromLTWH(bounds.left, bounds.top, w, bounds.height);
      second = Rect.fromLTWH(
        bounds.left + w,
        bounds.top,
        bounds.width - w,
        bounds.height,
      );
    } else {
      final h = bounds.height * fraction;
      first = Rect.fromLTWH(bounds.left, bounds.top, bounds.width, h);
      second = Rect.fromLTWH(
        bounds.left,
        bounds.top + h,
        bounds.width,
        bounds.height - h,
      );
    }

    _layoutRow(areas, rects, start, split, first);
    _layoutRow(areas, rects, split, end, second);
  }
}

class _TrendsLineChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final trendsAsync = ref.watch(trendsProvider);

    return trendsAsync.when(
      loading: () => _chartLoading(),
      error: (e, _) => _chartError(e),
      data: (items) {
        if (items.isEmpty) return _chartEmpty('No trend data available');

        // Group by make
        final byMake = <String, List<TrendItem>>{};
        for (final item in items) {
          byMake.putIfAbsent(item.make, () => []).add(item);
        }

        final makeColors = _assignColors(byMake.keys.toList());
        final allYears = items.map((e) => e.year).toSet().toList()..sort();
        final minYear = allYears.first.toDouble();
        final maxYear = allYears.last.toDouble();

        final lines = <LineChartBarData>[];
        for (final entry in byMake.entries) {
          final sorted = entry.value..sort((a, b) => a.year.compareTo(b.year));
          lines.add(
            LineChartBarData(
              spots: sorted
                  .map((e) => FlSpot(e.year.toDouble(), e.avgPrice))
                  .toList(),
              color: makeColors[entry.key],
              barWidth: 2,
              dotData: const FlDotData(show: true),
              isCurved: true,
              preventCurveOverShooting: true,
            ),
          );
        }

        return SizedBox(
          height: 250,
          child: Column(
            children: [
              // Legend
              Wrap(
                spacing: 12,
                children: makeColors.entries
                    .map((e) => _LegendDot(color: e.value, label: e.key))
                    .toList(),
              ),
              const SizedBox(height: 8),
              Expanded(
                child: LineChart(
                  LineChartData(
                    lineBarsData: lines,
                    minX: minYear,
                    maxX: maxYear,
                    gridData: FlGridData(
                      show: true,
                      drawVerticalLine: false,
                      getDrawingHorizontalLine: (_) =>
                          FlLine(color: AppTheme.gray100, strokeWidth: 1),
                    ),
                    titlesData: FlTitlesData(
                      leftTitles: AxisTitles(
                        sideTitles: SideTitles(
                          showTitles: true,
                          reservedSize: 55,
                          getTitlesWidget: (v, _) => Text(
                            _shortPrice(v),
                            style: TextStyle(
                              fontSize: 10,
                              color: AppTheme.gray400,
                            ),
                          ),
                        ),
                      ),
                      bottomTitles: AxisTitles(
                        sideTitles: SideTitles(
                          showTitles: true,
                          getTitlesWidget: (v, _) => Text(
                            v.toInt().toString(),
                            style: TextStyle(
                              fontSize: 10,
                              color: AppTheme.gray400,
                            ),
                          ),
                        ),
                      ),
                      topTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false),
                      ),
                      rightTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false),
                      ),
                    ),
                    borderData: FlBorderData(show: false),
                    lineTouchData: LineTouchData(
                      touchTooltipData: LineTouchTooltipData(
                        getTooltipItems: (spots) => spots
                            .map(
                              (s) => LineTooltipItem(
                                '${Fmt.price(s.y)}\n${s.x.toInt()}',
                                const TextStyle(
                                  fontSize: 11,
                                  color: Colors.white,
                                ),
                              ),
                            )
                            .toList(),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _GeoBarChart extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final geoAsync = ref.watch(geoProvider);

    return geoAsync.when(
      loading: () => _chartLoading(),
      error: (e, _) => _chartError(e),
      data: (items) {
        if (items.isEmpty) return _chartEmpty('No geographic data available');

        // Aggregate by country
        final byCountry = <String, double>{};
        for (final item in items) {
          byCountry[item.country] = item.avgPrice;
        }

        final countries = byCountry.keys.toList();
        final countryColors = _assignColors(countries);

        return SizedBox(
          height: 250,
          child: BarChart(
            BarChartData(
              barGroups: List.generate(countries.length, (i) {
                final country = countries[i];
                return BarChartGroupData(
                  x: i,
                  barRods: [
                    BarChartRodData(
                      toY: byCountry[country]!,
                      color: countryColors[country],
                      width: 20,
                      borderRadius: const BorderRadius.vertical(
                        top: Radius.circular(4),
                      ),
                    ),
                  ],
                );
              }),
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                getDrawingHorizontalLine: (_) =>
                    FlLine(color: AppTheme.gray100, strokeWidth: 1),
              ),
              titlesData: FlTitlesData(
                leftTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 55,
                    getTitlesWidget: (v, _) => Text(
                      _shortPrice(v),
                      style: TextStyle(fontSize: 10, color: AppTheme.gray400),
                    ),
                  ),
                ),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    getTitlesWidget: (v, _) {
                      final idx = v.toInt();
                      if (idx < 0 || idx >= countries.length) {
                        return const SizedBox.shrink();
                      }
                      return Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(
                          countries[idx],
                          style: TextStyle(
                            fontSize: 10,
                            color: AppTheme.gray400,
                          ),
                        ),
                      );
                    },
                  ),
                ),
                topTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false),
                ),
                rightTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false),
                ),
              ),
              borderData: FlBorderData(show: false),
              barTouchData: BarTouchData(
                touchTooltipData: BarTouchTooltipData(
                  getTooltipItem: (group, gi, rod, ri) {
                    final country = countries[group.x];
                    return BarTooltipItem(
                      '$country\n${Fmt.price(rod.toY)}',
                      const TextStyle(fontSize: 11, color: Colors.white),
                    );
                  },
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// Value Map Tab
// ---------------------------------------------------------------------------

class _ValueMapTab extends ConsumerWidget {
  const _ValueMapTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final valueMapAsync = ref.watch(valueMapProvider);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SectionHeading('Value Map'),
          const SizedBox(height: 8),
          valueMapAsync.when(
            loading: () => _chartLoading(),
            error: (e, _) => _chartError(e),
            data: (items) {
              if (items.isEmpty) {
                return _chartEmpty('No value map data available');
              }

              final maxCount = items.fold<int>(
                1,
                (m, i) => i.listingCount > m ? i.listingCount : m,
              );

              return SizedBox(
                height: 300,
                child: ScatterChart(
                  ScatterChartData(
                    scatterSpots: items.map((item) {
                      final radius =
                          4.0 + (item.listingCount / maxCount) * 16.0;
                      return ScatterSpot(
                        item.medianPrice,
                        item.avgScore,
                        dotPainter: FlDotCirclePainter(
                          radius: radius,
                          color: AppTheme.blue600.withValues(alpha: 0.6),
                          strokeWidth: 1,
                          strokeColor: AppTheme.blue600,
                        ),
                      );
                    }).toList(),
                    gridData: FlGridData(
                      show: true,
                      getDrawingHorizontalLine: (_) =>
                          FlLine(color: AppTheme.gray100, strokeWidth: 1),
                      getDrawingVerticalLine: (_) =>
                          FlLine(color: AppTheme.gray100, strokeWidth: 1),
                    ),
                    titlesData: FlTitlesData(
                      leftTitles: AxisTitles(
                        axisNameWidget: Text(
                          'Score',
                          style: TextStyle(
                            fontSize: 11,
                            color: AppTheme.gray500,
                          ),
                        ),
                        sideTitles: SideTitles(
                          showTitles: true,
                          reservedSize: 35,
                          getTitlesWidget: (v, _) => Text(
                            v.toStringAsFixed(1),
                            style: TextStyle(
                              fontSize: 10,
                              color: AppTheme.gray400,
                            ),
                          ),
                        ),
                      ),
                      bottomTitles: AxisTitles(
                        axisNameWidget: Text(
                          'Price (EUR)',
                          style: TextStyle(
                            fontSize: 11,
                            color: AppTheme.gray500,
                          ),
                        ),
                        sideTitles: SideTitles(
                          showTitles: true,
                          reservedSize: 30,
                          getTitlesWidget: (v, _) => Text(
                            _shortPrice(v),
                            style: TextStyle(
                              fontSize: 10,
                              color: AppTheme.gray400,
                            ),
                          ),
                        ),
                      ),
                      topTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false),
                      ),
                      rightTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false),
                      ),
                    ),
                    borderData: FlBorderData(
                      show: true,
                      border: Border(
                        left: BorderSide(color: AppTheme.gray200),
                        bottom: BorderSide(color: AppTheme.gray200),
                      ),
                    ),
                    scatterTouchData: ScatterTouchData(
                      enabled: true,
                      touchTooltipData: ScatterTouchTooltipData(
                        getTooltipItems: (spot) {
                          // Find matching item
                          final match = items.where(
                            (i) =>
                                i.medianPrice == spot.x && i.avgScore == spot.y,
                          );
                          final label = match.isNotEmpty
                              ? '${match.first.make} ${match.first.model}'
                              : '';
                          return ScatterTooltipItem(
                            '$label\n${Fmt.price(spot.x)}\nScore: ${spot.y.toStringAsFixed(1)}',
                            textStyle: const TextStyle(
                              fontSize: 11,
                              color: Colors.white,
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Price Index Tab
// ---------------------------------------------------------------------------

class _PriceIndexTab extends ConsumerWidget {
  const _PriceIndexTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final priceIndexAsync = ref.watch(priceIndexProvider);

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SectionHeading('Price Index'),
          const SizedBox(height: 8),
          priceIndexAsync.when(
            loading: () => _chartLoading(),
            error: (e, _) => _chartError(e),
            data: (items) {
              if (items.isEmpty) {
                return _chartEmpty('No price index data available');
              }

              // Group by make
              final byMake = <String, List<PriceIndexItem>>{};
              for (final item in items) {
                byMake.putIfAbsent(item.make, () => []).add(item);
              }

              final makeColors = _assignColors(byMake.keys.toList());
              final allYears = items.map((e) => e.year).toSet().toList()
                ..sort();
              final minYear = allYears.first.toDouble();
              final maxYear = allYears.last.toDouble();

              final lines = <LineChartBarData>[];
              for (final entry in byMake.entries) {
                final sorted = entry.value
                  ..sort((a, b) => a.year.compareTo(b.year));
                lines.add(
                  LineChartBarData(
                    spots: sorted
                        .map((e) => FlSpot(e.year.toDouble(), e.indexValue))
                        .toList(),
                    color: makeColors[entry.key],
                    barWidth: 2,
                    dotData: const FlDotData(show: true),
                    isCurved: true,
                    preventCurveOverShooting: true,
                  ),
                );
              }

              return SizedBox(
                height: 280,
                child: Column(
                  children: [
                    Wrap(
                      spacing: 12,
                      children: makeColors.entries
                          .map((e) => _LegendDot(color: e.value, label: e.key))
                          .toList(),
                    ),
                    const SizedBox(height: 8),
                    Expanded(
                      child: LineChart(
                        LineChartData(
                          lineBarsData: lines,
                          minX: minYear,
                          maxX: maxYear,
                          gridData: FlGridData(
                            show: true,
                            drawVerticalLine: false,
                            getDrawingHorizontalLine: (_) =>
                                FlLine(color: AppTheme.gray100, strokeWidth: 1),
                          ),
                          titlesData: FlTitlesData(
                            leftTitles: AxisTitles(
                              sideTitles: SideTitles(
                                showTitles: true,
                                reservedSize: 40,
                                getTitlesWidget: (v, _) => Text(
                                  v.toStringAsFixed(0),
                                  style: TextStyle(
                                    fontSize: 10,
                                    color: AppTheme.gray400,
                                  ),
                                ),
                              ),
                            ),
                            bottomTitles: AxisTitles(
                              sideTitles: SideTitles(
                                showTitles: true,
                                getTitlesWidget: (v, _) => Text(
                                  v.toInt().toString(),
                                  style: TextStyle(
                                    fontSize: 10,
                                    color: AppTheme.gray400,
                                  ),
                                ),
                              ),
                            ),
                            topTitles: const AxisTitles(
                              sideTitles: SideTitles(showTitles: false),
                            ),
                            rightTitles: const AxisTitles(
                              sideTitles: SideTitles(showTitles: false),
                            ),
                          ),
                          borderData: FlBorderData(show: false),
                          lineTouchData: LineTouchData(
                            touchTooltipData: LineTouchTooltipData(
                              getTooltipItems: (spots) => spots
                                  .map(
                                    (s) => LineTooltipItem(
                                      'Index: ${s.y.toStringAsFixed(1)}\n${s.x.toInt()}',
                                      const TextStyle(
                                        fontSize: 11,
                                        color: Colors.white,
                                      ),
                                    ),
                                  )
                                  .toList(),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

class _SectionHeading extends StatelessWidget {
  final String text;
  const _SectionHeading(this.text);

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
    );
  }
}

class _LegendDot extends StatelessWidget {
  final Color color;
  final String label;

  const _LegendDot({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(fontSize: 11, color: AppTheme.gray500)),
      ],
    );
  }
}

Widget _chartLoading() {
  return const SizedBox(
    height: 200,
    child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
  );
}

Widget _chartError(Object error) {
  return SizedBox(
    height: 200,
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, size: 32, color: AppTheme.red600),
          const SizedBox(height: 8),
          Text(
            error.toString(),
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, color: AppTheme.gray500),
          ),
        ],
      ),
    ),
  );
}

Widget _chartEmpty(String message) {
  return SizedBox(
    height: 200,
    child: Center(
      child: Text(
        message,
        style: TextStyle(fontSize: 14, color: AppTheme.gray400),
      ),
    ),
  );
}

String _shortPrice(double v) {
  if (v >= 1000000) return '${(v / 1000000).toStringAsFixed(1)}M';
  if (v >= 1000) return '${(v / 1000).toStringAsFixed(0)}k';
  return v.toStringAsFixed(0);
}

const _palette = [
  Color(0xFF2563EB), // blue
  Color(0xFFDC2626), // red
  Color(0xFF16A34A), // green
  Color(0xFFF59E0B), // amber
  Color(0xFF8B5CF6), // violet
  Color(0xFFEC4899), // pink
  Color(0xFF06B6D4), // cyan
  Color(0xFFF97316), // orange
  Color(0xFF14B8A6), // teal
  Color(0xFF6366F1), // indigo
];

Map<String, Color> _assignColors(List<String> keys) {
  final map = <String, Color>{};
  for (var i = 0; i < keys.length; i++) {
    map[keys[i]] = _palette[i % _palette.length];
  }
  return map;
}
