import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shimmer/shimmer.dart';

import 'package:carhero/config/theme.dart';
import 'package:carhero/models/garage.dart';
import 'package:carhero/providers/garage_provider.dart';
import 'package:carhero/utils/formatters.dart';
import 'package:carhero/screens/chat/widgets/chat_sidebar.dart';

class GarageScreen extends ConsumerWidget {
  const GarageScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final garageAsync = ref.watch(garageProvider);

    return Scaffold(
      drawer: const ChatSidebar(),
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        title: const Text('My Garage'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add),
            tooltip: 'Add Car',
            onPressed: () => _showAddCarSheet(context, ref),
          ),
        ],
      ),
      body: garageAsync.when(
        loading: () => _buildShimmer(),
        error: (error, stack) => _buildError(context, ref, error),
        data: (cars) {
          if (cars.isEmpty) {
            return _buildEmpty(context, ref);
          }
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(garageProvider);
            },
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: cars.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (context, index) {
                return _GarageCarCard(
                  car: cars[index],
                  onDelete: () async {
                    await ref
                        .read(garageProvider.notifier)
                        .deleteCar(cars[index].id);
                  },
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
        itemCount: 3,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, __) => Container(
          height: 160,
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(8),
          ),
        ),
      ),
    );
  }

  Widget _buildEmpty(BuildContext context, WidgetRef ref) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.directions_car_outlined,
            size: 64,
            color: AppTheme.gray400,
          ),
          const SizedBox(height: 16),
          Text(
            'No cars in your garage',
            style: TextStyle(fontSize: 18, color: AppTheme.gray500),
          ),
          const SizedBox(height: 8),
          Text(
            'Add your car to track its value and costs.',
            style: TextStyle(fontSize: 14, color: AppTheme.gray400),
          ),
          const SizedBox(height: 24),
          ElevatedButton.icon(
            onPressed: () => _showAddCarSheet(context, ref),
            icon: const Icon(Icons.add),
            label: const Text('Add Car'),
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
              'Failed to load garage',
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
              onPressed: () => ref.invalidate(garageProvider),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  void _showAddCarSheet(BuildContext context, WidgetRef ref) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => _AddCarBottomSheet(
        onAdd: (request) async {
          await ref.read(garageProvider.notifier).addCar(request);
          if (ctx.mounted) Navigator.pop(ctx);
        },
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Add Car Bottom Sheet
// ---------------------------------------------------------------------------

class _AddCarBottomSheet extends StatefulWidget {
  final Future<void> Function(AddGarageCarRequest) onAdd;

  const _AddCarBottomSheet({required this.onAdd});

  @override
  State<_AddCarBottomSheet> createState() => _AddCarBottomSheetState();
}

class _AddCarBottomSheetState extends State<_AddCarBottomSheet> {
  final _formKey = GlobalKey<FormState>();
  final _makeCtrl = TextEditingController();
  final _modelCtrl = TextEditingController();
  final _yearCtrl = TextEditingController();
  final _mileageCtrl = TextEditingController();
  final _priceCtrl = TextEditingController();
  String _fuelType = 'Petrol';
  bool _submitting = false;

  static const _fuelTypes = [
    'Petrol',
    'Diesel',
    'Hybrid',
    'Electric',
    'Plugin Hybrid',
    'LPG',
    'CNG',
  ];

  @override
  void dispose() {
    _makeCtrl.dispose();
    _modelCtrl.dispose();
    _yearCtrl.dispose();
    _mileageCtrl.dispose();
    _priceCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _submitting = true);

    try {
      final request = AddGarageCarRequest(
        make: _makeCtrl.text.trim(),
        model: _modelCtrl.text.trim(),
        year: int.parse(_yearCtrl.text.trim()),
        mileageKm: _mileageCtrl.text.isNotEmpty
            ? int.tryParse(_mileageCtrl.text.trim())
            : null,
        purchasePriceEur: _priceCtrl.text.isNotEmpty
            ? double.tryParse(_priceCtrl.text.trim())
            : null,
        fuelType: _fuelType,
      );
      await widget.onAdd(request);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to add car: $e'),
            backgroundColor: AppTheme.red600,
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Handle
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppTheme.gray200,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                'Add Car to Garage',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 16),

              TextFormField(
                controller: _makeCtrl,
                decoration: const InputDecoration(labelText: 'Make'),
                textCapitalization: TextCapitalization.words,
                validator: (v) =>
                    (v == null || v.trim().isEmpty) ? 'Required' : null,
              ),
              const SizedBox(height: 12),

              TextFormField(
                controller: _modelCtrl,
                decoration: const InputDecoration(labelText: 'Model'),
                textCapitalization: TextCapitalization.words,
                validator: (v) =>
                    (v == null || v.trim().isEmpty) ? 'Required' : null,
              ),
              const SizedBox(height: 12),

              TextFormField(
                controller: _yearCtrl,
                decoration: const InputDecoration(labelText: 'Year'),
                keyboardType: TextInputType.number,
                validator: (v) {
                  if (v == null || v.trim().isEmpty) return 'Required';
                  final year = int.tryParse(v.trim());
                  if (year == null || year < 1950 || year > 2026) {
                    return 'Enter a valid year';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 12),

              TextFormField(
                controller: _mileageCtrl,
                decoration: const InputDecoration(labelText: 'Mileage (km)'),
                keyboardType: TextInputType.number,
              ),
              const SizedBox(height: 12),

              TextFormField(
                controller: _priceCtrl,
                decoration: const InputDecoration(
                  labelText: 'Purchase Price (EUR)',
                ),
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
              ),
              const SizedBox(height: 12),

              DropdownButtonFormField<String>(
                value: _fuelType,
                decoration: const InputDecoration(labelText: 'Fuel Type'),
                items: _fuelTypes
                    .map((f) => DropdownMenuItem(value: f, child: Text(f)))
                    .toList(),
                onChanged: (v) {
                  if (v != null) setState(() => _fuelType = v);
                },
              ),
              const SizedBox(height: 20),

              ElevatedButton(
                onPressed: _submitting ? null : _submit,
                child: _submitting
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Add Car'),
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Garage Car Card
// ---------------------------------------------------------------------------

class _GarageCarCard extends ConsumerStatefulWidget {
  final GarageCar car;
  final VoidCallback onDelete;

  const _GarageCarCard({required this.car, required this.onDelete});

  @override
  ConsumerState<_GarageCarCard> createState() => _GarageCarCardState();
}

class _GarageCarCardState extends ConsumerState<_GarageCarCard> {
  bool _tcoExpanded = false;
  TcoCost? _tco;
  bool _tcoLoading = false;
  String? _tcoError;

  Future<void> _loadTco() async {
    if (_tco != null) {
      setState(() => _tcoExpanded = !_tcoExpanded);
      return;
    }

    setState(() {
      _tcoExpanded = true;
      _tcoLoading = true;
      _tcoError = null;
    });

    try {
      final service = ref.read(garageServiceProvider);
      final tco = await service.getTco(widget.car.id);
      if (mounted) {
        setState(() {
          _tco = tco;
          _tcoLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _tcoError = e.toString();
          _tcoLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final car = widget.car;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title + delete
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${car.make} ${car.model}${car.variant.isNotEmpty ? ' ${car.variant}' : ''}',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${car.year}',
                        style: TextStyle(fontSize: 14, color: AppTheme.gray500),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  icon: Icon(Icons.delete_outline, color: AppTheme.red600),
                  tooltip: 'Delete',
                  onPressed: () => _confirmDelete(context),
                ),
              ],
            ),
            const SizedBox(height: 8),

            // Info chips
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                if (car.mileageKm != null)
                  _Chip(Icons.speed, Fmt.mileage(car.mileageKm)),
                if (car.fuelType.isNotEmpty)
                  _Chip(Icons.local_gas_station, car.fuelType),
                if (car.comparableCount > 0)
                  _Chip(
                    Icons.compare_arrows,
                    '${car.comparableCount} comparable',
                  ),
              ],
            ),
            const SizedBox(height: 10),

            // Purchase price vs estimated value
            Row(
              children: [
                Expanded(
                  child: _ValueColumn(
                    label: 'Purchase Price',
                    value: car.purchasePriceEur != null
                        ? Fmt.price(car.purchasePriceEur)
                        : 'N/A',
                  ),
                ),
                Container(width: 1, height: 36, color: AppTheme.gray200),
                Expanded(
                  child: _ValueColumn(
                    label: 'Market Value',
                    value: car.estimatedValue != null
                        ? Fmt.price(car.estimatedValue!.toDouble())
                        : 'N/A',
                    valueColor: _getValueColor(car),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),

            // View TCO expandable
            InkWell(
              onTap: _loadTco,
              borderRadius: BorderRadius.circular(8),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Row(
                  children: [
                    Icon(
                      _tcoExpanded ? Icons.expand_less : Icons.expand_more,
                      size: 20,
                      color: AppTheme.blue600,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      'View TCO',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.blue600,
                      ),
                    ),
                  ],
                ),
              ),
            ),

            // TCO expanded content
            if (_tcoExpanded) ...[
              if (_tcoLoading)
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                )
              else if (_tcoError != null)
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    'Error loading TCO: $_tcoError',
                    style: TextStyle(fontSize: 13, color: AppTheme.red600),
                  ),
                )
              else if (_tco != null)
                _TcoTable(tco: _tco!),
            ],
          ],
        ),
      ),
    );
  }

  Color? _getValueColor(GarageCar car) {
    if (car.purchasePriceEur == null || car.estimatedValue == null) {
      return null;
    }
    if (car.estimatedValue! > car.purchasePriceEur!) {
      return AppTheme.green600;
    } else if (car.estimatedValue! < car.purchasePriceEur!) {
      return AppTheme.red600;
    }
    return null;
  }

  Future<void> _confirmDelete(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete Car'),
        content: Text(
          'Remove "${widget.car.make} ${widget.car.model}" from your garage?',
        ),
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
    );
    if (confirmed == true) widget.onDelete();
  }
}

// ---------------------------------------------------------------------------
// TCO Table
// ---------------------------------------------------------------------------

class _TcoTable extends StatelessWidget {
  final TcoCost tco;

  const _TcoTable({required this.tco});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.gray50,
        borderRadius: BorderRadius.circular(8),
      ),
      padding: const EdgeInsets.all(12),
      child: Table(
        columnWidths: const {0: FlexColumnWidth(2), 1: FlexColumnWidth(1.5)},
        children: [
          _row('Fuel', Fmt.price(tco.fuelAnnualEur.toDouble())),
          _row('Insurance', Fmt.price(tco.insuranceAnnualEur.toDouble())),
          _row('Maintenance', Fmt.price(tco.maintenanceAnnualEur.toDouble())),
          _row('Depreciation', Fmt.price(tco.depreciationAnnualEur.toDouble())),
          _dividerRow(),
          _row(
            'Total Annual',
            Fmt.price(tco.totalAnnualEur.toDouble()),
            bold: true,
          ),
          _row(
            'Total Monthly',
            Fmt.price(tco.totalMonthlyEur.toDouble()),
            bold: true,
          ),
          _row(
            'Cost per km',
            'EUR ${tco.costPerKmEur.toStringAsFixed(2)}',
            bold: true,
          ),
        ],
      ),
    );
  }

  TableRow _row(String label, String value, {bool bold = false}) {
    return TableRow(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 13,
              color: AppTheme.gray500,
              fontWeight: bold ? FontWeight.w600 : FontWeight.normal,
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Text(
            value,
            textAlign: TextAlign.right,
            style: TextStyle(
              fontSize: 13,
              fontWeight: bold ? FontWeight.w600 : FontWeight.normal,
            ),
          ),
        ),
      ],
    );
  }

  TableRow _dividerRow() {
    return TableRow(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Divider(color: AppTheme.gray200, height: 1),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Divider(color: AppTheme.gray200, height: 1),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Shared helper widgets
// ---------------------------------------------------------------------------

class _ValueColumn extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;

  const _ValueColumn({
    required this.label,
    required this.value,
    this.valueColor,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: TextStyle(fontSize: 11, color: AppTheme.gray400)),
        const SizedBox(height: 2),
        Text(
          value,
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w600,
            color: valueColor,
          ),
        ),
      ],
    );
  }
}

class _Chip extends StatelessWidget {
  final IconData icon;
  final String label;

  const _Chip(this.icon, this.label);

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
