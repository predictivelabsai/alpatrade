import 'package:flutter/material.dart';
import 'package:alpatrade/config/theme.dart';

class ChatInputBar extends StatefulWidget {
  final bool isStreaming;
  final bool voiceActive;
  final ValueChanged<String> onSend;
  final VoidCallback onMic;

  /// Owned by the parent so quick-action cards can prefill the field.
  final TextEditingController controller;
  final FocusNode focusNode;

  const ChatInputBar({
    super.key,
    required this.isStreaming,
    required this.voiceActive,
    required this.onSend,
    required this.onMic,
    required this.controller,
    required this.focusNode,
  });

  @override
  State<ChatInputBar> createState() => _ChatInputBarState();
}

class _ChatInputBarState extends State<ChatInputBar> {
  TextEditingController get _controller => widget.controller;
  FocusNode get _focusNode => widget.focusNode;
  bool _hasText = false;

  @override
  void initState() {
    super.initState();
    _hasText = _controller.text.trim().isNotEmpty;
    _controller.addListener(_onTextChanged);
  }

  void _onTextChanged() {
    final hasText = _controller.text.trim().isNotEmpty;
    if (hasText != _hasText) setState(() => _hasText = hasText);
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
    _controller.removeListener(_onTextChanged);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;

    return Container(
      padding: EdgeInsets.fromLTRB(
        8,
        8,
        8,
        8 + (bottom > 0 ? 0 : MediaQuery.of(context).padding.bottom),
      ),
      decoration: BoxDecoration(
        color: AppTheme.bgElev,
        border: Border(top: BorderSide(color: AppTheme.line, width: 0.5)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          _MicButton(active: widget.voiceActive, onTap: widget.onMic),
          const SizedBox(width: 6),
          Expanded(
            child: Container(
              constraints: const BoxConstraints(maxHeight: 120),
              decoration: BoxDecoration(
                color: AppTheme.bg,
                borderRadius: BorderRadius.circular(24),
                border: Border.all(color: AppTheme.line),
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
                  hintText: 'Ask about positions, P&L, news, backtests…',
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

class _MicButton extends StatelessWidget {
  final bool active;
  final VoidCallback onTap;

  const _MicButton({required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: active ? AppTheme.accent : AppTheme.bgRaise,
        shape: BoxShape.circle,
        border: Border.all(color: active ? AppTheme.accent : AppTheme.line),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          customBorder: const CircleBorder(),
          child: Center(
            child: Icon(
              active ? Icons.stop : Icons.mic_none,
              size: 20,
              color: active ? Colors.white : AppTheme.inkMuted,
            ),
          ),
        ),
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
        color: canSend ? AppTheme.accent : AppTheme.bgRaise,
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
                      color: AppTheme.inkDim,
                    ),
                  )
                : Icon(
                    Icons.arrow_upward,
                    size: 20,
                    color: canSend ? Colors.white : AppTheme.inkDim,
                  ),
          ),
        ),
      ),
    );
  }
}
