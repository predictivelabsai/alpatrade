import 'package:flutter/material.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/models/listing.dart';

class ListingCard extends StatelessWidget {
  final CarListing listing;
  final bool compact;

  const ListingCard({super.key, required this.listing, this.compact = false});

  /// Convenience constructor from raw JSON (used in artifact rendering).
  factory ListingCard.fromJson(
    Map<String, dynamic> json, {
    bool compact = false,
  }) {
    return ListingCard(listing: CarListing.fromJson(json), compact: compact);
  }

  Color _tierColor(int? tier) {
    switch (tier) {
      case 1:
        return AppTheme.green600;
      case 2:
        return const Color(0xFFEAB308); // amber/yellow
      case 3:
        return AppTheme.gray400;
      default:
        return AppTheme.gray400;
    }
  }

  String _tierLabel(int? tier) {
    switch (tier) {
      case 1:
        return 'Tier 1';
      case 2:
        return 'Tier 2';
      case 3:
        return 'Tier 3';
      default:
        return '';
    }
  }

  void _openSource() {
    if (listing.sourceUrl.isNotEmpty) {
      launchUrl(
        Uri.parse(listing.sourceUrl),
        mode: LaunchMode.externalApplication,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    if (compact) return _buildCompact(context);
    return _buildFull(context);
  }

  Widget _buildFull(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: _openSource,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Image
            if (listing.imageUrls != null && listing.imageUrls!.isNotEmpty)
              SizedBox(
                height: 160,
                width: double.infinity,
                child: CachedNetworkImage(
                  imageUrl: listing.imageUrls!.first,
                  fit: BoxFit.cover,
                  placeholder: (_, __) => Container(
                    color: AppTheme.gray100,
                    child: Center(
                      child: Icon(
                        Icons.directions_car,
                        size: 40,
                        color: AppTheme.gray400,
                      ),
                    ),
                  ),
                  errorWidget: (_, __, ___) => Container(
                    color: AppTheme.gray100,
                    child: Center(
                      child: Icon(
                        Icons.directions_car,
                        size: 40,
                        color: AppTheme.gray400,
                      ),
                    ),
                  ),
                ),
              ),

            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Title row
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              listing.displayTitle,
                              style: const TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w600,
                                height: 1.3,
                              ),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                            if (listing.year != null)
                              Text(
                                '${listing.year}',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: AppTheme.gray500,
                                ),
                              ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      // Price badge
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 5,
                        ),
                        decoration: BoxDecoration(
                          color: AppTheme.ink,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          listing.priceFormatted,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                  ),

                  const SizedBox(height: 10),

                  // Details row
                  Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    children: [
                      if (listing.mileageKm != null)
                        _DetailChip(
                          icon: Icons.speed,
                          label: listing.mileageFormatted,
                        ),
                      if (listing.fuelType.isNotEmpty)
                        _DetailChip(
                          icon: Icons.local_gas_station,
                          label: listing.fuelType,
                        ),
                      if (listing.transmission.isNotEmpty)
                        _DetailChip(
                          icon: Icons.settings,
                          label: listing.transmission,
                        ),
                      if (listing.powerHp != null)
                        _DetailChip(
                          icon: Icons.bolt,
                          label: '${listing.powerHp} hp',
                        ),
                    ],
                  ),

                  const SizedBox(height: 8),

                  // Footer row: country/provider + investment tier
                  Row(
                    children: [
                      if (listing.country.isNotEmpty ||
                          listing.provider.isNotEmpty)
                        Expanded(
                          child: Text(
                            [
                              listing.country,
                              listing.provider,
                            ].where((s) => s.isNotEmpty).join(' / '),
                            style: TextStyle(
                              fontSize: 12,
                              color: AppTheme.gray500,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      if (listing.tier != null) ...[
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 3,
                          ),
                          decoration: BoxDecoration(
                            color: _tierColor(
                              listing.tier,
                            ).withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: _tierColor(
                                listing.tier,
                              ).withValues(alpha: 0.4),
                            ),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                Icons.trending_up,
                                size: 12,
                                color: _tierColor(listing.tier),
                              ),
                              const SizedBox(width: 4),
                              Text(
                                _tierLabel(listing.tier),
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w600,
                                  color: _tierColor(listing.tier),
                                ),
                              ),
                              if (listing.investmentScore != null) ...[
                                const SizedBox(width: 4),
                                Text(
                                  '${listing.investmentScore}',
                                  style: TextStyle(
                                    fontSize: 11,
                                    color: _tierColor(listing.tier),
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCompact(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: _openSource,
        child: SizedBox(
          height: 170,
          child: Row(
            children: [
              // Thumbnail
              if (listing.imageUrls != null && listing.imageUrls!.isNotEmpty)
                SizedBox(
                  width: 110,
                  child: CachedNetworkImage(
                    imageUrl: listing.imageUrls!.first,
                    fit: BoxFit.cover,
                    height: double.infinity,
                    placeholder: (_, __) => Container(
                      color: AppTheme.gray100,
                      child: Center(
                        child: Icon(
                          Icons.directions_car,
                          size: 28,
                          color: AppTheme.gray400,
                        ),
                      ),
                    ),
                    errorWidget: (_, __, ___) => Container(
                      color: AppTheme.gray100,
                      child: Center(
                        child: Icon(
                          Icons.directions_car,
                          size: 28,
                          color: AppTheme.gray400,
                        ),
                      ),
                    ),
                  ),
                )
              else
                Container(
                  width: 110,
                  color: AppTheme.gray100,
                  child: Center(
                    child: Icon(
                      Icons.directions_car,
                      size: 28,
                      color: AppTheme.gray400,
                    ),
                  ),
                ),

              // Details
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        listing.displayTitle,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          height: 1.2,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      if (listing.year != null)
                        Text(
                          '${listing.year}',
                          style: TextStyle(
                            fontSize: 11,
                            color: AppTheme.gray500,
                          ),
                        ),
                      const SizedBox(height: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: AppTheme.ink,
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          listing.priceFormatted,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      const Spacer(),
                      if (listing.mileageKm != null)
                        Text(
                          listing.mileageFormatted,
                          style: TextStyle(
                            fontSize: 11,
                            color: AppTheme.gray500,
                          ),
                        ),
                      const SizedBox(height: 2),
                      Row(
                        children: [
                          if (listing.fuelType.isNotEmpty)
                            Text(
                              listing.fuelType,
                              style: TextStyle(
                                fontSize: 11,
                                color: AppTheme.gray500,
                              ),
                            ),
                          if (listing.fuelType.isNotEmpty &&
                              listing.country.isNotEmpty)
                            Text(
                              ' / ',
                              style: TextStyle(
                                fontSize: 11,
                                color: AppTheme.gray400,
                              ),
                            ),
                          if (listing.country.isNotEmpty)
                            Text(
                              listing.country,
                              style: TextStyle(
                                fontSize: 11,
                                color: AppTheme.gray500,
                              ),
                            ),
                        ],
                      ),
                      if (listing.tier != null) ...[
                        const SizedBox(height: 4),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 6,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: _tierColor(
                              listing.tier,
                            ).withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            _tierLabel(listing.tier),
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w600,
                              color: _tierColor(listing.tier),
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DetailChip extends StatelessWidget {
  final IconData icon;
  final String label;

  const _DetailChip({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: AppTheme.gray50,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppTheme.gray200, width: 0.5),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: AppTheme.gray500),
          const SizedBox(width: 4),
          Text(label, style: TextStyle(fontSize: 12, color: AppTheme.gray500)),
        ],
      ),
    );
  }
}
