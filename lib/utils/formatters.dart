import 'package:intl/intl.dart';

class Fmt {
  static String price(double? v) {
    if (v == null) return 'N/A';
    return 'EUR ${NumberFormat('#,##0', 'en_US').format(v.round())}';
  }

  static String mileage(int? v) {
    if (v == null) return '';
    return '${NumberFormat('#,##0', 'en_US').format(v)} km';
  }

  static String priceChange(int? v) {
    if (v == null || v == 0) return '';
    final sign = v > 0 ? '+' : '';
    return '$sign${NumberFormat('#,##0', 'en_US').format(v)} EUR';
  }

  static String dateShort(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    try {
      return DateFormat('MMM d, y').format(DateTime.parse(iso));
    } catch (_) {
      return iso;
    }
  }
}
