import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/models/chat.dart';

class ToolExecutionCard extends StatelessWidget {
  final ToolCall toolCall;
  final bool isActive;

  const ToolExecutionCard({
    super.key,
    required this.toolCall,
    required this.isActive,
  });

  /// Human-readable label for a tool name like "search_listings" -> "Search Listings"
  String get _displayName {
    return toolCall.name
        .replaceAll('_', ' ')
        .split(' ')
        .map((w) => w.isNotEmpty ? '${w[0].toUpperCase()}${w.substring(1)}' : w)
        .join(' ');
  }

  String _prettyJson(Map<String, dynamic> json) {
    try {
      const encoder = JsonEncoder.withIndent('  ');
      return encoder.convert(json);
    } catch (_) {
      return json.toString();
    }
  }

  String _truncate(String text, int maxLen) {
    if (text.length <= maxLen) return text;
    return '${text.substring(0, maxLen)}...';
  }

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(10),
      clipBehavior: Clip.antiAlias,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.82,
        ),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: isActive
                ? AppTheme.blue600.withValues(alpha: 0.4)
                : AppTheme.gray200,
          ),
        ),
        child: Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: const EdgeInsets.symmetric(horizontal: 12),
            childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
            leading: isActive
                ? SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: AppTheme.blue600,
                    ),
                  )
                : Icon(Icons.check_circle, size: 16, color: AppTheme.green600),
            title: Text(
              _displayName,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
            ),
            trailing: Text(
              isActive ? 'Calling...' : 'Done',
              style: TextStyle(
                fontSize: 11,
                color: isActive ? AppTheme.blue600 : AppTheme.green600,
                fontWeight: FontWeight.w500,
              ),
            ),
            children: [
              // Args section
              if (toolCall.args.isNotEmpty) ...[
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    'Arguments',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.gray500,
                    ),
                  ),
                ),
                const SizedBox(height: 4),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: AppTheme.gray50,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    _prettyJson(toolCall.args),
                    style: TextStyle(
                      fontSize: 11,
                      fontFamily: 'monospace',
                      color: AppTheme.gray500,
                      height: 1.4,
                    ),
                  ),
                ),
              ],

              // Output section
              if (toolCall.output != null && toolCall.output!.isNotEmpty) ...[
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    'Output',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.gray500,
                    ),
                  ),
                ),
                const SizedBox(height: 4),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: AppTheme.gray50,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    _truncate(toolCall.output!, 500),
                    style: TextStyle(
                      fontSize: 11,
                      fontFamily: 'monospace',
                      color: AppTheme.gray500,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
