import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_chart/fl_chart.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/analytics.dart';
import 'package:carhero/providers/analytics_provider.dart';
import 'package:carhero/utils/formatters.dart';
import 'package:carhero/screens/chat/widgets/chat_sidebar.dart';

class AnalyticsScreen extends ConsumerStatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  ConsumerState<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends ConsumerState<AnalyticsScreen> {
  final _queryController = TextEditingController();

  static const _suggestions = [
    'Average price by brand',
    'Top 10 cheapest Porsche 911s',
    'Listings count by country',
    'Average mileage by fuel type',
    'Price distribution of BMW M3',
    'Most expensive cars under 50k km',
    'Electric cars by price and range',
    'Price trend by model year for Audi',
  ];

  @override
  void dispose() {
    _queryController.dispose();
    super.dispose();
  }

  void _runQuery(String query) {
    if (query.trim().isEmpty) return;
    _queryController.text = query;
    ref.read(analyticsProvider.notifier).runQuery(query.trim());
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(analyticsProvider);

    return Scaffold(
      drawer: const ChatSidebar(),
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Analytics'),
            Text(
              'Text to SQL + Charts',
              style: TextStyle(fontSize: 12, color: AppTheme.gray500),
            ),
          ],
        ),
        toolbarHeight: 60,
      ),
      body: Column(
        children: [
          // Query input
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _queryController,
                    decoration: const InputDecoration(
                      hintText: 'Ask a question about the car market...',
                      prefixIcon: Icon(Icons.auto_awesome, size: 20),
                    ),
                    textInputAction: TextInputAction.search,
                    onSubmitted: _runQuery,
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  height: 48,
                  child: ElevatedButton(
                    onPressed: state.status == AnalyticsStatus.loading
                        ? null
                        : () => _runQuery(_queryController.text),
                    child: const Text('Run'),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),

          // Suggestion chips
          SizedBox(
            height: 36,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              itemCount: _suggestions.length,
              separatorBuilder: (_, __) => const SizedBox(width: 6),
              itemBuilder: (_, i) => ActionChip(
                label: Text(
                  _suggestions[i],
                  style: const TextStyle(fontSize: 12),
                ),
                onPressed: () => _runQuery(_suggestions[i]),
                visualDensity: VisualDensity.compact,
              ),
            ),
          ),
          const SizedBox(height: 8),

          Divider(color: AppTheme.gray200, height: 1),

          // Result area
          Expanded(child: _buildResultArea(state)),
        ],
      ),
    );
  }

  Widget _buildResultArea(AnalyticsState state) {
    switch (state.status) {
      case AnalyticsStatus.idle:
        return _buildIdleState();
      case AnalyticsStatus.loading:
        return const Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(strokeWidth: 2),
              SizedBox(height: 16),
              Text('Generating SQL and running query...'),
            ],
          ),
        );
      case AnalyticsStatus.error:
        return _buildErrorState(state.error ?? 'Unknown error');
      case AnalyticsStatus.result:
        return _buildResultContent(state.result!);
    }
  }

  Widget _buildIdleState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.analytics_outlined, size: 64, color: AppTheme.gray400),
          const SizedBox(height: 16),
          Text(
            'Ask a question about the car market',
            style: TextStyle(fontSize: 16, color: AppTheme.gray500),
          ),
          const SizedBox(height: 8),
          Text(
            'Your question will be converted to SQL and visualized.',
            style: TextStyle(fontSize: 13, color: AppTheme.gray400),
          ),
        ],
      ),
    );
  }

  Widget _buildErrorState(String error) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48, color: AppTheme.red600),
            const SizedBox(height: 16),
            Text(
              'Query failed',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: AppTheme.ink,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              error,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: AppTheme.gray500),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => _runQuery(_queryController.text),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildResultContent(AnalyticsResult result) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Title
          if (result.title.isNotEmpty) ...[
            Text(
              result.title,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 12),
          ],

          // SQL display
          if (result.sql.isNotEmpty) ...[
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppTheme.gray50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppTheme.gray200),
              ),
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Text(
                  result.sql,
                  style: TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12,
                    color: AppTheme.gray500,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 16),
          ],

          // Chart
          if (result.data != null &&
              result.data!.isNotEmpty &&
              result.chartType != null) ...[
            _AnalyticsChart(result: result),
            const SizedBox(height: 16),
          ],

          // Data table
          if (result.data != null && result.data!.isNotEmpty) ...[
            Text(
              '${result.rows} rows',
              style: TextStyle(fontSize: 13, color: AppTheme.gray500),
            ),
            const SizedBox(height: 8),
            _AnalyticsDataTable(result: result),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Analytics Chart
// ---------------------------------------------------------------------------

class _AnalyticsChart extends StatelessWidget {
  final AnalyticsResult result;

  const _AnalyticsChart({required this.result});

  @override
  Widget build(BuildContext context) {
    final data = result.data!;
    final xCol = result.xColumn;
    final yCol = result.yColumn;

    if (xCol == null || yCol == null || data.isEmpty) {
      return const SizedBox.shrink();
    }

    switch (result.chartType) {
      case 'bar':
        return _buildBarChart(data, xCol, yCol);
      case 'line':
        return _buildLineChart(data, xCol, yCol);
      case 'scatter':
        return _buildScatterChart(data, xCol, yCol);
      default:
        return _buildBarChart(data, xCol, yCol);
    }
  }

  Widget _buildBarChart(
    List<Map<String, dynamic>> data,
    String xCol,
    String yCol,
  ) {
    final displayData = data.take(30).toList();
    final labels = displayData.map((r) => r[xCol]?.toString() ?? '').toList();

    return SizedBox(
      height: 250,
      child: BarChart(
        BarChartData(
          barGroups: List.generate(displayData.length, (i) {
            final yVal = _toDouble(displayData[i][yCol]);
            return BarChartGroupData(
              x: i,
              barRods: [
                BarChartRodData(
                  toY: yVal,
                  color: _barColor(i),
                  width: displayData.length > 15 ? 8 : 16,
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
                  _shortNum(v),
                  style: TextStyle(fontSize: 10, color: AppTheme.gray400),
                ),
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 40,
                getTitlesWidget: (v, _) {
                  final idx = v.toInt();
                  if (idx < 0 || idx >= labels.length) {
                    return const SizedBox.shrink();
                  }
                  return Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: RotatedBox(
                      quarterTurns: labels.length > 8 ? 1 : 0,
                      child: Text(
                        labels[idx].length > 10
                            ? '${labels[idx].substring(0, 10)}...'
                            : labels[idx],
                        style: TextStyle(fontSize: 9, color: AppTheme.gray400),
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
                final label = labels[group.x];
                return BarTooltipItem(
                  '$label\n${Fmt.price(rod.toY)}',
                  const TextStyle(fontSize: 11, color: Colors.white),
                );
              },
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildLineChart(
    List<Map<String, dynamic>> data,
    String xCol,
    String yCol,
  ) {
    final spots = <FlSpot>[];
    for (var i = 0; i < data.length; i++) {
      final x = _toDouble(data[i][xCol]);
      final y = _toDouble(data[i][yCol]);
      spots.add(FlSpot(x != 0 ? x : i.toDouble(), y));
    }

    if (spots.isEmpty) return const SizedBox.shrink();

    return SizedBox(
      height: 250,
      child: LineChart(
        LineChartData(
          lineBarsData: [
            LineChartBarData(
              spots: spots,
              color: AppTheme.blue600,
              barWidth: 2,
              dotData: FlDotData(show: spots.length < 30),
              isCurved: true,
              preventCurveOverShooting: true,
            ),
          ],
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
                  _shortNum(v),
                  style: TextStyle(fontSize: 10, color: AppTheme.gray400),
                ),
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                getTitlesWidget: (v, _) => Text(
                  _shortNum(v),
                  style: TextStyle(fontSize: 10, color: AppTheme.gray400),
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
        ),
      ),
    );
  }

  Widget _buildScatterChart(
    List<Map<String, dynamic>> data,
    String xCol,
    String yCol,
  ) {
    final spots = data.take(200).map((row) {
      return ScatterSpot(
        _toDouble(row[xCol]),
        _toDouble(row[yCol]),
        dotPainter: FlDotCirclePainter(
          radius: 5,
          color: AppTheme.blue600.withValues(alpha: 0.6),
          strokeWidth: 1,
          strokeColor: AppTheme.blue600,
        ),
      );
    }).toList();

    if (spots.isEmpty) return const SizedBox.shrink();

    return SizedBox(
      height: 250,
      child: ScatterChart(
        ScatterChartData(
          scatterSpots: spots,
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
                yCol,
                style: TextStyle(fontSize: 11, color: AppTheme.gray500),
              ),
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 55,
                getTitlesWidget: (v, _) => Text(
                  _shortNum(v),
                  style: TextStyle(fontSize: 10, color: AppTheme.gray400),
                ),
              ),
            ),
            bottomTitles: AxisTitles(
              axisNameWidget: Text(
                xCol,
                style: TextStyle(fontSize: 11, color: AppTheme.gray500),
              ),
              sideTitles: SideTitles(
                showTitles: true,
                getTitlesWidget: (v, _) => Text(
                  _shortNum(v),
                  style: TextStyle(fontSize: 10, color: AppTheme.gray400),
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
        ),
      ),
    );
  }

  double _toDouble(dynamic v) {
    if (v == null) return 0;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? 0;
  }

  Color _barColor(int index) {
    const palette = [
      Color(0xFF2563EB),
      Color(0xFFDC2626),
      Color(0xFF16A34A),
      Color(0xFFF59E0B),
      Color(0xFF8B5CF6),
      Color(0xFFEC4899),
      Color(0xFF06B6D4),
      Color(0xFFF97316),
      Color(0xFF14B8A6),
      Color(0xFF6366F1),
    ];
    return palette[index % palette.length];
  }

  String _shortNum(double v) {
    if (v.abs() >= 1000000) return '${(v / 1000000).toStringAsFixed(1)}M';
    if (v.abs() >= 1000) return '${(v / 1000).toStringAsFixed(0)}k';
    return v.toStringAsFixed(0);
  }
}

// ---------------------------------------------------------------------------
// Analytics Data Table
// ---------------------------------------------------------------------------

class _AnalyticsDataTable extends StatelessWidget {
  final AnalyticsResult result;

  const _AnalyticsDataTable({required this.result});

  @override
  Widget build(BuildContext context) {
    final data = result.data!;
    if (data.isEmpty) return const SizedBox.shrink();

    final columns = data.first.keys.toList();
    final displayRows = data.take(50).toList();

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowColor: WidgetStateProperty.all(AppTheme.gray50),
        border: TableBorder.all(color: AppTheme.gray200, width: 1),
        columnSpacing: 16,
        dataRowMinHeight: 36,
        dataRowMaxHeight: 48,
        columns: columns
            .map(
              (col) => DataColumn(
                label: Text(
                  col,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            )
            .toList(),
        rows: displayRows
            .map(
              (row) => DataRow(
                cells: columns
                    .map(
                      (col) => DataCell(
                        Text(
                          _formatCellValue(row[col]),
                          style: const TextStyle(fontSize: 12),
                        ),
                      ),
                    )
                    .toList(),
              ),
            )
            .toList(),
      ),
    );
  }

  String _formatCellValue(dynamic value) {
    if (value == null) return '';
    if (value is double) {
      if (value == value.roundToDouble()) return value.toInt().toString();
      return value.toStringAsFixed(2);
    }
    return value.toString();
  }
}
