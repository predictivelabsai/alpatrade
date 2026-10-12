import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:alpatrade/config/theme.dart';

sealed class MarkdownContentBlock {
  const MarkdownContentBlock();
}

class MarkdownTextBlock extends MarkdownContentBlock {
  final String text;

  const MarkdownTextBlock(this.text);
}

class MarkdownTableBlock extends MarkdownContentBlock {
  final List<String> headers;
  final List<List<String>> rows;
  final String source;

  const MarkdownTableBlock({
    required this.headers,
    required this.rows,
    required this.source,
  });
}

/// Splits complete GitHub-style Markdown tables from surrounding prose.
///
/// Incomplete tables are deliberately kept as text while an answer streams.
List<MarkdownContentBlock> parseMarkdownContent(String source) {
  final lines = source.split('\n');
  final blocks = <MarkdownContentBlock>[];
  final prose = <String>[];

  void flushProse() {
    final text = prose.join('\n').trim();
    if (text.isNotEmpty) blocks.add(MarkdownTextBlock(text));
    prose.clear();
  }

  var index = 0;
  while (index < lines.length) {
    if (index + 1 < lines.length) {
      final headers = _parseTableRow(lines[index]);
      final separators = _parseTableRow(lines[index + 1]);
      final isTable =
          headers.length >= 2 &&
          separators.length == headers.length &&
          separators.every(_isTableSeparator);

      if (isTable) {
        final rows = <List<String>>[];
        var next = index + 2;
        while (next < lines.length) {
          final row = _parseTableRow(lines[next]);
          if (row.length != headers.length) break;
          rows.add(row);
          next++;
        }

        // Wait for at least one data row before switching the streaming UI.
        if (rows.isNotEmpty) {
          flushProse();
          blocks.add(
            MarkdownTableBlock(
              headers: headers,
              rows: rows,
              source: lines.sublist(index, next).join('\n'),
            ),
          );
          index = next;
          continue;
        }
      }
    }

    prose.add(lines[index]);
    index++;
  }

  flushProse();
  return blocks;
}

List<String> _parseTableRow(String line) {
  final trimmed = line.trim();
  if (!trimmed.contains('|')) return const [];

  var body = trimmed;
  if (body.startsWith('|')) body = body.substring(1);
  if (body.endsWith('|') && !body.endsWith(r'\|')) {
    body = body.substring(0, body.length - 1);
  }

  final cells = <String>[];
  final buffer = StringBuffer();
  var escaped = false;
  for (final rune in body.runes) {
    final character = String.fromCharCode(rune);
    if (escaped) {
      buffer.write(character);
      escaped = false;
    } else if (character == r'\') {
      escaped = true;
    } else if (character == '|') {
      cells.add(buffer.toString().trim());
      buffer.clear();
    } else {
      buffer.write(character);
    }
  }
  if (escaped) buffer.write(r'\');
  cells.add(buffer.toString().trim());
  return cells;
}

bool _isTableSeparator(String value) =>
    RegExp(r'^:?-{3,}:?$').hasMatch(value.trim());

class ResponsiveMarkdown extends StatelessWidget {
  final String data;
  final bool selectable;

  const ResponsiveMarkdown({
    super.key,
    required this.data,
    this.selectable = true,
  });

  @override
  Widget build(BuildContext context) {
    final blocks = parseMarkdownContent(data);
    return LayoutBuilder(
      builder: (context, constraints) {
        final useCards = constraints.maxWidth < 600;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var index = 0; index < blocks.length; index++) ...[
              if (index > 0) const SizedBox(height: 10),
              switch (blocks[index]) {
                MarkdownTextBlock(:final text) => _markdown(text),
                MarkdownTableBlock table =>
                  useCards
                      ? _MobileTable(table: table, selectable: selectable)
                      : SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: _markdown(table.source),
                        ),
              },
            ],
          ],
        );
      },
    );
  }

  Widget _markdown(String text) => MarkdownBody(
    data: text,
    selectable: selectable,
    styleSheet: markdownStyleSheet,
    onTapLink: (text, href, title) {
      if (href != null) {
        launchUrl(Uri.parse(href), mode: LaunchMode.externalApplication);
      }
    },
  );
}

class _MobileTable extends StatelessWidget {
  final MarkdownTableBlock table;
  final bool selectable;

  const _MobileTable({required this.table, required this.selectable});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var rowIndex = 0; rowIndex < table.rows.length; rowIndex++)
          Padding(
            padding: EdgeInsets.only(
              bottom: rowIndex == table.rows.length - 1 ? 0 : 8,
            ),
            child: _MobileTableRow(
              headers: table.headers,
              values: table.rows[rowIndex],
              selectable: selectable,
            ),
          ),
      ],
    );
  }
}

class _MobileTableRow extends StatelessWidget {
  final List<String> headers;
  final List<String> values;
  final bool selectable;

  const _MobileTableRow({
    required this.headers,
    required this.values,
    required this.selectable,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: [
        for (var i = 0; i < headers.length; i++)
          '${_plainText(headers[i])} ${_plainText(values[i])}',
      ].join(', '),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppTheme.bg,
          border: Border.all(color: AppTheme.line),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _plainText(values.first),
              style: TextStyle(
                color: AppTheme.ink,
                fontFamily: AppTheme.monoFont,
                fontSize: 15,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 10),
            LayoutBuilder(
              builder: (context, constraints) {
                const gap = 10.0;
                final itemWidth = (constraints.maxWidth - gap) / 2;
                return Wrap(
                  spacing: gap,
                  runSpacing: 10,
                  children: [
                    for (var i = 1; i < headers.length; i++)
                      SizedBox(
                        width: itemWidth,
                        child: _ValueCell(
                          label: _plainText(headers[i]),
                          value: _plainText(values[i]),
                          selectable: selectable,
                        ),
                      ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _ValueCell extends StatelessWidget {
  final String label;
  final String value;
  final bool selectable;

  const _ValueCell({
    required this.label,
    required this.value,
    required this.selectable,
  });

  @override
  Widget build(BuildContext context) {
    final valueStyle = TextStyle(
      color: _valueColor(label, value),
      fontFamily: AppTheme.monoFont,
      fontSize: 13,
      fontWeight: FontWeight.w600,
      height: 1.3,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            color: AppTheme.inkDim,
            fontSize: 10.5,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 2),
        if (selectable)
          SelectableText(value, style: valueStyle)
        else
          Text(value, style: valueStyle),
      ],
    );
  }
}

String _plainText(String value) => value
    .replaceAll(RegExp(r'\*\*|__|`'), '')
    .replaceAllMapped(RegExp(r'\[([^\]]+)\]\([^\)]+\)'), (match) => match[1]!)
    .trim();

Color _valueColor(String label, String value) {
  final semanticLabel = label.toLowerCase();
  final isPerformance =
      semanticLabel.contains('p&l') ||
      semanticLabel.contains('profit') ||
      semanticLabel.contains('return') ||
      semanticLabel.contains('change');
  if (!isPerformance) return AppTheme.ink;
  final trimmed = value.trim();
  if (trimmed.startsWith('+')) return AppTheme.gain;
  if (trimmed.startsWith('-') || trimmed.startsWith('(')) return AppTheme.loss;
  return AppTheme.inkMuted;
}

final markdownStyleSheet = MarkdownStyleSheet(
  p: TextStyle(color: AppTheme.ink, fontSize: 14, height: 1.5),
  h1: TextStyle(
    color: AppTheme.ink,
    fontSize: 20,
    fontWeight: FontWeight.w700,
    height: 1.3,
  ),
  h2: TextStyle(
    color: AppTheme.ink,
    fontSize: 17,
    fontWeight: FontWeight.w600,
    height: 1.3,
  ),
  h3: TextStyle(
    color: AppTheme.ink,
    fontSize: 15,
    fontWeight: FontWeight.w600,
    height: 1.3,
  ),
  code: TextStyle(
    backgroundColor: AppTheme.bgRaise,
    color: AppTheme.accentDeep,
    fontFamily: AppTheme.monoFont,
    fontSize: 13,
  ),
  codeblockDecoration: BoxDecoration(
    color: AppTheme.bgRaise,
    borderRadius: BorderRadius.circular(6),
  ),
  blockquoteDecoration: BoxDecoration(
    border: Border(left: BorderSide(color: AppTheme.accent, width: 3)),
  ),
  listBullet: TextStyle(color: AppTheme.ink, fontSize: 14),
  tableHead: TextStyle(fontWeight: FontWeight.w600, color: AppTheme.ink),
  tableBorder: TableBorder.all(color: AppTheme.line, width: 1),
  a: TextStyle(color: AppTheme.accent, decoration: TextDecoration.underline),
);
