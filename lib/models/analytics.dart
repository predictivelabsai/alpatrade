class AnalyticsResult {
  final String sql;
  final String title;
  final List<Map<String, dynamic>>? data;
  final String? chartType;
  final String? xColumn;
  final String? yColumn;
  final String? colorColumn;
  final int rows;

  const AnalyticsResult({
    this.sql = '',
    this.title = '',
    this.data,
    this.chartType,
    this.xColumn,
    this.yColumn,
    this.colorColumn,
    this.rows = 0,
  });

  factory AnalyticsResult.fromJson(Map<String, dynamic> json) =>
      AnalyticsResult(
        sql: json['sql'] as String? ?? '',
        title: json['title'] as String? ?? '',
        data: (json['data'] as List<dynamic>?)
            ?.map((e) => Map<String, dynamic>.from(e as Map))
            .toList(),
        chartType: json['chart_type'] as String?,
        xColumn: json['x_column'] as String?,
        yColumn: json['y_column'] as String?,
        colorColumn: json['color_column'] as String?,
        rows: json['rows'] as int? ?? 0,
      );
}
