import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import 'package:carhero/config/api_config.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/models/chat.dart';
import 'package:carhero/screens/chat/widgets/chat_message_bubble.dart';

class SharedSessionScreen extends StatefulWidget {
  final String token;

  const SharedSessionScreen({super.key, required this.token});

  @override
  State<SharedSessionScreen> createState() => _SharedSessionScreenState();
}

class _SharedSessionScreenState extends State<SharedSessionScreen> {
  bool _loading = true;
  String? _error;
  String _title = 'Shared Chat';
  List<ChatMessage> _messages = [];

  @override
  void initState() {
    super.initState();
    _loadSharedSession();
  }

  Future<void> _loadSharedSession() async {
    try {
      final dio = Dio(BaseOptions(baseUrl: ApiConfig.baseUrl));
      final response = await dio.get<Map<String, dynamic>>(
        '/shared/${widget.token}',
      );
      final data = response.data!;
      if (!mounted) return;
      final rawMessages = data['messages'] as List<dynamic>? ?? [];
      setState(() {
        _loading = false;
        _title = data['title'] as String? ?? 'Shared Chat';
        _messages = rawMessages
            .map(
              (m) => ChatMessage(
                role: m['role'] as String? ?? 'assistant',
                content: m['content'] as String? ?? '',
                agentSlug: m['agent_slug'] as String?,
              ),
            )
            .toList();
      });
    } on DioException catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e.response?.statusCode == 404
            ? 'This shared chat was not found or has expired.'
            : 'Failed to load shared chat. Please try again.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'An unexpected error occurred.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'Kenri.ai',
              style: TextStyle(
                fontFamily: 'Inter',
                fontWeight: FontWeight.w800,
                fontSize: 17,
                color: AppTheme.ink,
              ),
            ),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: AppTheme.gray100,
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                'Shared Chat',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w500,
                  color: AppTheme.gray500,
                ),
              ),
            ),
          ],
        ),
        centerTitle: true,
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.error_outline, size: 48, color: AppTheme.red600),
              const SizedBox(height: 16),
              Text(
                'Failed to load shared chat',
                style: TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.ink,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 14,
                  color: AppTheme.gray500,
                  height: 1.5,
                ),
              ),
              const SizedBox(height: 24),
              OutlinedButton(
                onPressed: () {
                  setState(() {
                    _loading = true;
                    _error = null;
                  });
                  _loadSharedSession();
                },
                style: OutlinedButton.styleFrom(
                  side: BorderSide(color: AppTheme.ink),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8),
                  ),
                ),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    if (_messages.isEmpty) {
      return Center(
        child: Text(
          'No messages in this shared chat.',
          style: TextStyle(fontSize: 14, color: AppTheme.gray500),
        ),
      );
    }

    return Column(
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          color: AppTheme.gray50,
          child: Row(
            children: [
              Icon(Icons.link, size: 16, color: AppTheme.gray400),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _title,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                    color: AppTheme.gray500,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
            itemCount: _messages.length,
            itemBuilder: (context, index) {
              return ChatMessageBubble(message: _messages[index]);
            },
          ),
        ),
      ],
    );
  }
}
