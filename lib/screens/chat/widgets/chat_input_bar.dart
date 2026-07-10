import 'package:flutter/material.dart';
import 'package:carhero/config/theme.dart';

class ChatInputBar extends StatefulWidget {
  final bool isStreaming;
  final ValueChanged<String> onSend;

  const ChatInputBar({
    super.key,
    required this.isStreaming,
    required this.onSend,
  });

  @override
  State<ChatInputBar> createState() => _ChatInputBarState();
}

class _ChatInputBarState extends State<ChatInputBar> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();
  bool _hasText = false;

  @override
  void initState() {
    super.initState();
    _controller.addListener(() {
      final hasText = _controller.text.trim().isNotEmpty;
      if (hasText != _hasText) {
        setState(() => _hasText = hasText);
      }
    });
  }

  void _send() {
    final text = _controller.text.trim();
    if (text.isEmpty || widget.isStreaming) return;
    widget.onSend(text);
    _controller.clear();
    _focusNode.requestFocus();
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;

    return Container(
      padding: EdgeInsets.fromLTRB(
        12,
        8,
        8,
        8 + (bottom > 0 ? 0 : MediaQuery.of(context).padding.bottom),
      ),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: AppTheme.gray200, width: 0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Container(
              constraints: const BoxConstraints(maxHeight: 120),
              decoration: BoxDecoration(
                color: AppTheme.gray50,
                borderRadius: BorderRadius.circular(24),
                border: Border.all(color: AppTheme.gray200),
              ),
              child: TextField(
                controller: _controller,
                focusNode: _focusNode,
                enabled: !widget.isStreaming,
                maxLines: null,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _send(),
                style: const TextStyle(fontSize: 14, height: 1.4),
                decoration: const InputDecoration(
                  hintText: 'Search for a car, compare models...',
                  border: InputBorder.none,
                  enabledBorder: InputBorder.none,
                  focusedBorder: InputBorder.none,
                  contentPadding: EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 10,
                  ),
                  filled: false,
                ),
              ),
            ),
          ),
          const SizedBox(width: 6),
          _SendButton(
            canSend: _hasText && !widget.isStreaming,
            isStreaming: widget.isStreaming,
            onTap: _send,
          ),
        ],
      ),
    );
  }
}

class _SendButton extends StatelessWidget {
  final bool canSend;
  final bool isStreaming;
  final VoidCallback onTap;

  const _SendButton({
    required this.canSend,
    required this.isStreaming,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: canSend ? AppTheme.ink : AppTheme.gray200,
        shape: BoxShape.circle,
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: canSend ? onTap : null,
          customBorder: const CircleBorder(),
          child: Center(
            child: isStreaming
                ? SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: AppTheme.gray500,
                    ),
                  )
                : Icon(
                    Icons.arrow_upward,
                    size: 20,
                    color: canSend ? Colors.white : AppTheme.gray400,
                  ),
          ),
        ),
      ),
    );
  }
}
