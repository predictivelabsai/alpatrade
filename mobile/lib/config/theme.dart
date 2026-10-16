import 'package:flutter/material.dart';

/// AlpaTrade palette — mirrors the web app (static/app.css): warm cream
/// surfaces, forest-green accent, JetBrains Mono for numbers/tickers.
class AppTheme {
  // Brand
  static const _accent = Color(0xFF1F5D43); // --accent
  static const _accentDim = Color(0xFFCFE5DA); // --accent-dim
  static const _accentDeep = Color(0xFF164A35); // --accent-deep

  // Surfaces
  static const _bg = Color(0xFFF7F6F1); // --bg
  static const _bgElev = Color(0xFFFFFFFF); // --bg-elev
  static const _bgRaise = Color(0xFFEFEDE4); // --bg-raise

  // Ink
  static const _ink = Color(0xFF14231B); // --ink
  static const _inkMuted = Color(0xFF415046); // --ink-muted
  static const _inkDim = Color(0xFF7A867E); // --ink-dim

  // Lines
  static const _line = Color(0xFFE3DFD2); // --line
  static const _lineBr = Color(0xFFCFC8B4); // --line-br

  // Semantic (P&L)
  static const _red = Color(0xFFB83A3A); // --red / loss
  static const _green = Color(0xFF1F6B45); // --green / gain

  static const _white = Color(0xFFFFFFFF);

  // Public accessors (mono font name for numeric/ticker text)
  static const String monoFont = 'JetBrains Mono';

  static Color get accent => _accent;
  static Color get accentDim => _accentDim;
  static Color get accentDeep => _accentDeep;
  static Color get bg => _bg;
  static Color get bgElev => _bgElev;
  static Color get bgRaise => _bgRaise;
  static Color get ink => _ink;
  static Color get inkMuted => _inkMuted;
  static Color get inkDim => _inkDim;
  static Color get line => _line;
  static Color get lineBr => _lineBr;
  static Color get gain => _green;
  static Color get loss => _red;

  // ---- Backwards-compatible aliases used across older widgets ----
  static Color get gray50 => _bg;
  static Color get gray100 => _bgRaise;
  static Color get gray200 => _line;
  static Color get gray400 => _lineBr;
  static Color get gray500 => _inkDim;
  static Color get green600 => _green;
  static Color get red600 => _red;
  static Color get blue600 => _accent;

  /// Positive/negative tint for a signed value.
  static Color pnlColor(num? v) => (v ?? 0) > 0
      ? _green
      : (v ?? 0) < 0
      ? _red
      : _inkDim;

  static ThemeData get light => ThemeData(
    useMaterial3: true,
    fontFamily: 'Inter',
    scaffoldBackgroundColor: _bg,
    colorScheme: const ColorScheme.light(
      primary: _accent,
      onPrimary: _white,
      secondary: _accentDeep,
      onSecondary: _white,
      surface: _bgElev,
      onSurface: _ink,
      surfaceContainerHighest: _bgRaise,
      outline: _line,
      error: _red,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: _bgElev,
      foregroundColor: _ink,
      elevation: 0,
      scrolledUnderElevation: 1,
      titleTextStyle: TextStyle(
        fontFamily: 'Inter',
        fontWeight: FontWeight.w600,
        fontSize: 17,
        color: _ink,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: _bgElev,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: _line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: _line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: _accent, width: 1.5),
      ),
      hintStyle: const TextStyle(color: _inkDim, fontSize: 14),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: _accent,
        foregroundColor: _white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        textStyle: const TextStyle(
          fontFamily: 'Inter',
          fontWeight: FontWeight.w600,
          fontSize: 14,
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: _accent,
        textStyle: const TextStyle(
          fontFamily: 'Inter',
          fontWeight: FontWeight.w600,
          fontSize: 14,
        ),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: _bgElev,
      selectedColor: _accentDim,
      labelStyle: const TextStyle(fontSize: 13, color: _ink),
      side: const BorderSide(color: _line),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
    ),
    bottomNavigationBarTheme: const BottomNavigationBarThemeData(
      backgroundColor: _bgElev,
      selectedItemColor: _accent,
      unselectedItemColor: _inkDim,
      type: BottomNavigationBarType.fixed,
      elevation: 8,
      selectedLabelStyle: TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
      unselectedLabelStyle: TextStyle(fontSize: 11),
    ),
    dividerTheme: const DividerThemeData(color: _line, thickness: 1),
    cardTheme: CardThemeData(
      color: _bgElev,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: const BorderSide(color: _line),
      ),
    ),
  );
}
