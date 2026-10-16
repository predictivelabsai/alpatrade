class ApiConfig {
  /// REST + SSE chat base (api_app.py). Override with --dart-define=API_BASE_URL=...
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://api.alpatrade.chat',
  );

  /// Realtime voice WebSocket (agui_app.py -> x.ai realtime proxy).
  /// Override with --dart-define=VOICE_WS_URL=wss://...
  static const String voiceWsUrl = String.fromEnvironment(
    'VOICE_WS_URL',
    defaultValue: 'wss://alpatrade.chat/ws/voice',
  );

  static const Duration connectTimeout = Duration(seconds: 10);
  static const Duration receiveTimeout = Duration(seconds: 30);
}
