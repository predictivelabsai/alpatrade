class SavedSearch {
  final int id;
  final String name;
  final Map<String, dynamic> filters;
  final int lastCount;
  final bool notifyEmail;
  final String createdAt;

  const SavedSearch({
    required this.id,
    required this.name,
    this.filters = const {},
    this.lastCount = 0,
    this.notifyEmail = false,
    this.createdAt = '',
  });

  factory SavedSearch.fromJson(Map<String, dynamic> json) => SavedSearch(
    id: json['id'] as int,
    name: json['name'] as String,
    filters: (json['filters'] as Map<String, dynamic>?) ?? const {},
    lastCount: json['last_count'] as int? ?? 0,
    notifyEmail: json['notify_email'] as bool? ?? false,
    createdAt: json['created_at'] as String? ?? '',
  );
}
