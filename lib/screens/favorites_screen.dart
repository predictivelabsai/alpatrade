import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shimmer/shimmer.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/favorite.dart';
import 'package:carhero/providers/favorite_provider.dart';
import 'package:carhero/utils/formatters.dart';
import 'package:carhero/screens/chat/widgets/chat_sidebar.dart';

class FavoritesScreen extends ConsumerWidget {
  const FavoritesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final favoritesAsync = ref.watch(favoritesProvider);

    return Scaffold(
      drawer: const ChatSidebar(),
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        title: const Text('Favorites'),
      ),
      body: favoritesAsync.when(
        loading: () => _buildShimmer(),
        error: (error, stack) => _buildError(context, ref, error),
        data: (favorites) {
          if (favorites.isEmpty) {
            return _buildEmpty();
          }
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(favoritesProvider);
            },
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: favorites.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (context, index) {
                return _FavoriteCard(
                  favorite: favorites[index],
                  onDelete: () async {
                    await ref
                        .read(favoritesProvider.notifier)
                        .remove(favorites[index].id);
                  },
                  onEditNote: () =>
                      _showEditNoteDialog(context, ref, favorites[index]),
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
        itemCount: 5,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, __) => Container(
          height: 140,
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
          Icon(Icons.favorite_border, size: 64, color: AppTheme.gray400),
          const SizedBox(height: 16),
          Text(
            'No favorites yet',
            style: TextStyle(fontSize: 18, color: AppTheme.gray500),
          ),
          const SizedBox(height: 8),
          Text(
            'Save listings you like and they will appear here.',
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
              'Failed to load favorites',
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
              onPressed: () => ref.invalidate(favoritesProvider),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _showEditNoteDialog(
    BuildContext context,
    WidgetRef ref,
    Favorite fav,
  ) async {
    final controller = TextEditingController(text: fav.note);
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Edit Note'),
        content: TextField(
          controller: controller,
          maxLines: 3,
          decoration: const InputDecoration(hintText: 'Add a note...'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, controller.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (result != null) {
      await ref.read(favoritesProvider.notifier).updateNote(fav.id, result);
    }
  }
}

class _FavoriteCard extends StatelessWidget {
  final Favorite favorite;
  final VoidCallback onDelete;
  final VoidCallback onEditNote;

  const _FavoriteCard({
    required this.favorite,
    required this.onDelete,
    required this.onEditNote,
  });

  @override
  Widget build(BuildContext context) {
    return Dismissible(
      key: ValueKey(favorite.id),
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
                title: const Text('Remove Favorite'),
                content: Text(
                  'Remove "${favorite.displayTitle}" from favorites?',
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx, false),
                    child: const Text('Cancel'),
                  ),
                  ElevatedButton(
                    onPressed: () => Navigator.pop(ctx, true),
                    child: const Text('Remove'),
                  ),
                ],
              ),
            ) ??
            false;
      },
      onDismissed: (_) => onDelete(),
      child: Card(
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: () => _openUrl(context),
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
                        favorite.displayTitle,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    if (favorite.year != null)
                      Text(
                        '${favorite.year}',
                        style: TextStyle(fontSize: 14, color: AppTheme.gray500),
                      ),
                  ],
                ),
                const SizedBox(height: 8),

                // Price row
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: AppTheme.ink,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        favorite.priceFormatted,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    if (favorite.priceChange != null &&
                        favorite.priceChange != 0) ...[
                      const SizedBox(width: 8),
                      Icon(
                        favorite.priceChange! < 0
                            ? Icons.trending_down
                            : Icons.trending_up,
                        size: 16,
                        color: favorite.priceChange! < 0
                            ? AppTheme.green600
                            : AppTheme.red600,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        Fmt.priceChange(favorite.priceChange),
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w500,
                          color: favorite.priceChange! < 0
                              ? AppTheme.green600
                              : AppTheme.red600,
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 8),

                // Chips row
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: [
                    if (favorite.mileageKm != null)
                      _InfoChip(
                        icon: Icons.speed,
                        label: Fmt.mileage(favorite.mileageKm),
                      ),
                    if (favorite.fuelType.isNotEmpty)
                      _InfoChip(
                        icon: Icons.local_gas_station,
                        label: favorite.fuelType,
                      ),
                    if (favorite.transmission.isNotEmpty)
                      _InfoChip(
                        icon: Icons.settings,
                        label: favorite.transmission,
                      ),
                  ],
                ),
                const SizedBox(height: 6),

                // Country/provider row
                if (favorite.country.isNotEmpty || favorite.provider.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      [
                        favorite.country,
                        favorite.provider,
                      ].where((s) => s.isNotEmpty).join(' - '),
                      style: TextStyle(fontSize: 12, color: AppTheme.gray500),
                    ),
                  ),

                // Note row
                if (favorite.note.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          favorite.note,
                          style: TextStyle(
                            fontSize: 13,
                            fontStyle: FontStyle.italic,
                            color: AppTheme.gray500,
                          ),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 8),
                      GestureDetector(
                        onTap: onEditNote,
                        child: Icon(
                          Icons.edit,
                          size: 16,
                          color: AppTheme.gray400,
                        ),
                      ),
                    ],
                  ),
                ] else ...[
                  const SizedBox(height: 4),
                  GestureDetector(
                    onTap: onEditNote,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.edit, size: 14, color: AppTheme.gray400),
                        const SizedBox(width: 4),
                        Text(
                          'Add note',
                          style: TextStyle(
                            fontSize: 12,
                            color: AppTheme.gray400,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _openUrl(BuildContext context) async {
    if (favorite.url.isEmpty) return;
    final uri = Uri.tryParse(favorite.url);
    if (uri != null && await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }
}

class _InfoChip extends StatelessWidget {
  final IconData icon;
  final String label;

  const _InfoChip({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        border: Border.all(color: AppTheme.gray200),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: AppTheme.gray500),
          const SizedBox(width: 4),
          Text(label, style: TextStyle(fontSize: 12, color: AppTheme.gray500)),
        ],
      ),
    );
  }
}
