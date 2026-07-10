import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shimmer/shimmer.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/saved_search.dart';
import 'package:carhero/providers/saved_search_provider.dart';
import 'package:carhero/screens/chat/widgets/chat_sidebar.dart';

class SavedSearchesScreen extends ConsumerWidget {
  const SavedSearchesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final searchesAsync = ref.watch(savedSearchesProvider);

    return Scaffold(
      drawer: const ChatSidebar(),
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        title: const Text('Saved Searches'),
      ),
      body: searchesAsync.when(
        loading: () => _buildShimmer(),
        error: (error, stack) => _buildError(context, ref, error),
        data: (searches) {
          if (searches.isEmpty) {
            return _buildEmpty();
          }
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(savedSearchesProvider);
            },
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: searches.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (context, index) {
                return _SavedSearchCard(
                  search: searches[index],
                  onDelete: () async {
                    await ref
                        .read(savedSearchesProvider.notifier)
                        .delete(searches[index].id);
                  },
                  onRun: () => _runSearch(context, ref, searches[index]),
                );
              },
            ),
          );
        },
      ),
    );
  }

  Widget _buildShimmer() {
    return Shimmer.fromColors(
      baseColor: AppTheme.gray100,
      highlightColor: AppTheme.gray50,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: 4,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, __) => Container(
          height: 100,
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(8),
          ),
        ),
      ),
    );
  }

  Widget _buildEmpty() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.search_off, size: 64, color: AppTheme.gray400),
          const SizedBox(height: 16),
          Text(
            'No saved searches yet',
            style: TextStyle(fontSize: 18, color: AppTheme.gray500),
          ),
          const SizedBox(height: 8),
          Text(
            'Save your search criteria to get notified of new listings.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 14, color: AppTheme.gray400),
          ),
        ],
      ),
    );
  }

  Widget _buildError(BuildContext context, WidgetRef ref, Object error) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48, color: AppTheme.red600),
            const SizedBox(height: 16),
            Text(
              'Failed to load saved searches',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: AppTheme.ink,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              error.toString(),
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: AppTheme.gray500),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => ref.invalidate(savedSearchesProvider),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _runSearch(
    BuildContext context,
    WidgetRef ref,
    SavedSearch search,
  ) async {
    try {
      final service = ref.read(savedSearchServiceProvider);
      final newCount = await service.check(search.id);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Found $newCount new listings for "${search.name}"'),
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error checking search: $e'),
            backgroundColor: AppTheme.red600,
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    }
  }
}

class _SavedSearchCard extends StatelessWidget {
  final SavedSearch search;
  final VoidCallback onDelete;
  final VoidCallback onRun;

  const _SavedSearchCard({
    required this.search,
    required this.onDelete,
    required this.onRun,
  });

  List<String> get _activeFilterLabels {
    final labels = <String>[];
    for (final entry in search.filters.entries) {
      final key = entry.key;
      final value = entry.value;
      if (value == null) continue;
      if (value is String && value.isEmpty) continue;
      if (value is List && value.isEmpty) continue;

      final displayKey = key
          .replaceAll('_', ' ')
          .replaceAllMapped(RegExp(r'(^|\s)\w'), (m) => m[0]!.toUpperCase());

      if (value is List) {
        labels.add('$displayKey: ${value.join(", ")}');
      } else {
        labels.add('$displayKey: $value');
      }
    }
    return labels;
  }

  @override
  Widget build(BuildContext context) {
    final filterLabels = _activeFilterLabels;

    return Dismissible(
      key: ValueKey(search.id),
      direction: DismissDirection.endToStart,
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        decoration: BoxDecoration(
          color: AppTheme.red600,
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Icon(Icons.delete, color: Colors.white),
      ),
      confirmDismiss: (_) async {
        return await showDialog<bool>(
              context: context,
              builder: (ctx) => AlertDialog(
                title: const Text('Delete Saved Search'),
                content: Text('Delete "${search.name}"?'),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, false),
                    child: const Text('Cancel'),
                  ),
                  ElevatedButton(
                    onPressed: () => Navigator.pop(ctx, true),
                    child: const Text('Delete'),
                  ),
                ],
              ),
            ) ??
            false;
      },
      onDismissed: (_) => onDelete(),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Title row
              Row(
                children: [
                  Expanded(
                    child: Text(
                      search.name,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: AppTheme.blue600.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      '${search.lastCount} listings',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.blue600,
                      ),
                    ),
                  ),
                ],
              ),

              // Filter chips
              if (filterLabels.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: filterLabels.map((label) {
                    return Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: AppTheme.gray50,
                        border: Border.all(color: AppTheme.gray200),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        label,
                        style: TextStyle(fontSize: 11, color: AppTheme.gray500),
                      ),
                    );
                  }).toList(),
                ),
              ],

              const SizedBox(height: 10),

              // Run button
              Row(
                children: [
                  if (search.notifyEmail)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: Icon(
                        Icons.email_outlined,
                        size: 16,
                        color: AppTheme.gray400,
                      ),
                    ),
                  const Spacer(),
                  SizedBox(
                    height: 32,
                    child: ElevatedButton.icon(
                      onPressed: onRun,
                      icon: const Icon(Icons.play_arrow, size: 16),
                      label: const Text('Run'),
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        textStyle: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
