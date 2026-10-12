import 'package:intl/intl.dart';

/// Formatting helpers for trading data (USD paper account).
class Fmt {
  static final _money0 = NumberFormat('#,##0', 'en_US');
  static final _money2 = NumberFormat('#,##0.00', 'en_US');

  /// $1,234.56 (2dp) — for prices and per-share values.
  static String usd(num? v, {int decimals = 2}) {
    if (v == null) return '—';
    final f = decimals == 0 ? _money0 : _money2;
    final s = f.format(v.abs());
    return '${v < 0 ? '-' : ''}\$$s';
  }

  /// Signed money, e.g. +$1,234.56 / -$1,234.56 (for P&L).
  static String signedUsd(num? v, {int decimals = 2}) {
    if (v == null) return '—';
    final f = decimals == 0 ? _money0 : _money2;
    final sign = v > 0 ? '+' : (v < 0 ? '-' : '');
    return '$sign\$${f.format(v.abs())}';
  }

  /// 12.34% with optional sign.
  static String pct(num? v, {bool signed = false, int decimals = 2}) {
    if (v == null) return '—';
    final sign = signed && v > 0 ? '+' : '';
    return '$sign${v.toStringAsFixed(decimals)}%';
  }

  /// Compact share count (drops trailing .0).
  static String shares(num? v) {
    if (v == null) return '—';
    if (v == v.roundToDouble()) return _money0.format(v);
    return v.toString();
  }

  static String number(num? v, {int decimals = 2}) {
    if (v == null) return '—';
    return decimals == 0 ? _money0.format(v) : v.toStringAsFixed(decimals);
  }

  static String dateShort(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    try {
      return DateFormat('MMM d, y').format(DateTime.parse(iso).toLocal());
    } catch (_) {
      return iso;
    }
  }

  static String dateTimeShort(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    try {
      return DateFormat('MMM d, HH:mm').format(DateTime.parse(iso).toLocal());
    } catch (_) {
      return iso;
    }
  }

  /// Title-cases a strategy slug: buy_the_dip -> Buy The Dip.
  static String titleize(String? slug) {
    if (slug == null || slug.isEmpty) return '—';
    return slug
        .replaceAll('_', ' ')
        .replaceAll('-', ' ')
        .split(' ')
        .where((w) => w.isNotEmpty)
        .map((w) => '${w[0].toUpperCase()}${w.substring(1)}')
        .join(' ');
  }
}
