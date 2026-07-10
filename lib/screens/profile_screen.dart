import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:carhero/config/constants.dart';
import 'package:carhero/config/theme.dart';
import 'package:carhero/models/profile.dart';
import 'package:carhero/providers/auth_provider.dart';
import 'package:carhero/providers/profile_provider.dart';
import 'package:carhero/screens/chat/widgets/chat_sidebar.dart';

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  // --- Account controllers ---
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _phoneController = TextEditingController();
  final _countryController = TextEditingController();
  final _cityController = TextEditingController();
  String _currency = 'EUR';
  String _language = 'en';

  // --- Search Preferences ---
  final _budgetMinController = TextEditingController();
  final _budgetMaxController = TextEditingController();
  Set<String> _selectedMakes = {};
  Set<String> _selectedBodyTypes = {};
  Set<String> _selectedFuelTypes = {};
  String _transmission = 'Any';
  final _maxMileageController = TextEditingController();
  final _minYearController = TextEditingController();
  final _maxYearController = TextEditingController();

  // --- Notifications ---
  bool _notifyNewListings = true;
  bool _notifyPriceDrops = true;
  bool _notifyWeeklyDigest = false;

  bool _initialized = false;
  bool _savingAccount = false;
  bool _savingPrefs = false;
  bool _savingNotifications = false;

  static const _currencies = ['EUR', 'GBP', 'SEK', 'USD'];

  static const _languageLabels = <String, String>{
    'en': 'English',
    'et': 'Eesti',
    'de': 'Deutsch',
    'fr': 'Francais',
    'sv': 'Svenska',
    'lv': 'Latviesu',
    'no': 'Norsk',
    'da': 'Dansk',
    'pl': 'Polski',
    'nl': 'Nederlands',
    'fi': 'Suomi',
    'lt': 'Lietuviu',
  };

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    _phoneController.dispose();
    _countryController.dispose();
    _cityController.dispose();
    _budgetMinController.dispose();
    _budgetMaxController.dispose();
    _maxMileageController.dispose();
    _minYearController.dispose();
    _maxYearController.dispose();
    super.dispose();
  }

  void _populateFromProfile(UserProfile profile) {
    _nameController.text = profile.name;
    _emailController.text = profile.email;
    _phoneController.text = profile.phone;
    _countryController.text = profile.country;
    _cityController.text = profile.city;
    _currency = _currencies.contains(profile.currency)
        ? profile.currency
        : 'EUR';
    _language = AppConstants.supportedLocales.contains(profile.language)
        ? profile.language
        : 'en';

    if (profile.budgetMinEur != null) {
      _budgetMinController.text = profile.budgetMinEur!.toStringAsFixed(0);
    }
    if (profile.budgetMaxEur != null) {
      _budgetMaxController.text = profile.budgetMaxEur!.toStringAsFixed(0);
    }
    _selectedMakes = profile.preferredMakes.toSet();
    _selectedBodyTypes = profile.preferredBodyTypes.toSet();
    _selectedFuelTypes = profile.preferredFuelTypes.toSet();
    _transmission = profile.preferredTransmission ?? 'Any';
    if (profile.maxMileageKm != null) {
      _maxMileageController.text = profile.maxMileageKm.toString();
    }
    if (profile.minYear != null) {
      _minYearController.text = profile.minYear.toString();
    }
    if (profile.maxYear != null) {
      _maxYearController.text = profile.maxYear.toString();
    }

    _notifyNewListings = profile.notifyNewListings;
    _notifyPriceDrops = profile.notifyPriceDrops;
    _notifyWeeklyDigest = profile.notifyWeeklyDigest;
  }

  Future<void> _saveAccount() async {
    setState(() => _savingAccount = true);
    try {
      await ref
          .read(profileProvider.notifier)
          .updateProfile(
            UpdateProfileRequest(
              name: _nameController.text.trim(),
              phone: _phoneController.text.trim(),
              country: _countryController.text.trim(),
              city: _cityController.text.trim(),
              currency: _currency,
              language: _language,
            ),
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text('Account saved'),
          backgroundColor: AppTheme.green600,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to save account: $e'),
          backgroundColor: AppTheme.red600,
        ),
      );
    } finally {
      if (mounted) setState(() => _savingAccount = false);
    }
  }

  Future<void> _savePreferences() async {
    setState(() => _savingPrefs = true);
    try {
      final minBudget = double.tryParse(_budgetMinController.text.trim());
      final maxBudget = double.tryParse(_budgetMaxController.text.trim());
      final maxMileage = int.tryParse(_maxMileageController.text.trim());
      final minYear = int.tryParse(_minYearController.text.trim());
      final maxYear = int.tryParse(_maxYearController.text.trim());

      await ref
          .read(profileProvider.notifier)
          .updateProfile(
            UpdateProfileRequest(
              budgetMinEur: minBudget,
              budgetMaxEur: maxBudget,
              preferredMakes: _selectedMakes.toList(),
              preferredBodyTypes: _selectedBodyTypes.toList(),
              preferredFuelTypes: _selectedFuelTypes.toList(),
              preferredTransmission: _transmission == 'Any'
                  ? null
                  : _transmission,
              maxMileageKm: maxMileage,
              minYear: minYear,
              maxYear: maxYear,
            ),
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text('Preferences saved'),
          backgroundColor: AppTheme.green600,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to save preferences: $e'),
          backgroundColor: AppTheme.red600,
        ),
      );
    } finally {
      if (mounted) setState(() => _savingPrefs = false);
    }
  }

  Future<void> _saveNotifications() async {
    setState(() => _savingNotifications = true);
    try {
      await ref
          .read(profileProvider.notifier)
          .updateProfile(
            UpdateProfileRequest(
              notifyNewListings: _notifyNewListings,
              notifyPriceDrops: _notifyPriceDrops,
              notifyWeeklyDigest: _notifyWeeklyDigest,
            ),
          );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text('Notification settings saved'),
          backgroundColor: AppTheme.green600,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to save notifications: $e'),
          backgroundColor: AppTheme.red600,
        ),
      );
    } finally {
      if (mounted) setState(() => _savingNotifications = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profileAsync = ref.watch(profileProvider);

    // Pre-fill controllers once when profile loads
    profileAsync.whenData((profile) {
      if (profile != null && !_initialized) {
        _initialized = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) {
            setState(() => _populateFromProfile(profile));
          }
        });
      }
    });

    return Scaffold(
      drawer: const ChatSidebar(),
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
          ),
        ),
        title: const Text('Profile & Preferences'),
      ),
      body: profileAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(
              'Failed to load profile: $e',
              style: TextStyle(color: AppTheme.red600),
              textAlign: TextAlign.center,
            ),
          ),
        ),
        data: (profile) {
          if (profile == null) {
            return const Center(child: Text('Please log in to view profile.'));
          }
          return _buildForm();
        },
      ),
    );
  }

  Widget _buildForm() {
    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // ---- Section 1: Account ----
          _sectionHeader('Account'),
          const SizedBox(height: 12),
          _textField('Name', _nameController),
          const SizedBox(height: 12),
          _textField('Email', _emailController, readOnly: true),
          const SizedBox(height: 12),
          _textField(
            'Phone',
            _phoneController,
            keyboardType: TextInputType.phone,
          ),
          const SizedBox(height: 12),
          _textField('Country', _countryController),
          const SizedBox(height: 12),
          _textField('City', _cityController),
          const SizedBox(height: 12),
          _dropdownField<String>(
            label: 'Currency',
            value: _currency,
            items: _currencies
                .map((c) => DropdownMenuItem(value: c, child: Text(c)))
                .toList(),
            onChanged: (v) {
              if (v != null) setState(() => _currency = v);
            },
          ),
          const SizedBox(height: 12),
          _dropdownField<String>(
            label: 'Language',
            value: _language,
            items: AppConstants.supportedLocales.map((code) {
              final label = _languageLabels[code] ?? code;
              return DropdownMenuItem(value: code, child: Text(label));
            }).toList(),
            onChanged: (v) {
              if (v != null) setState(() => _language = v);
            },
          ),
          const SizedBox(height: 20),
          _saveButton('Save Account', _savingAccount, _saveAccount),

          const SizedBox(height: 32),
          const Divider(),
          const SizedBox(height: 16),

          // ---- Section 2: Search Preferences ----
          _sectionHeader('Search Preferences'),
          const SizedBox(height: 16),

          // Budget range
          Text(
            'Budget Range',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppTheme.gray500,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextFormField(
                  controller: _budgetMinController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    hintText: 'Min',
                    prefixText: 'EUR ',
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextFormField(
                  controller: _budgetMaxController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    hintText: 'Max',
                    prefixText: 'EUR ',
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),

          // Preferred Makes
          _chipGroupLabel('Preferred Makes'),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: AppConstants.brands.map((brand) {
              final selected = _selectedMakes.contains(brand);
              return FilterChip(
                label: Text(brand),
                selected: selected,
                selectedColor: AppTheme.ink,
                labelStyle: TextStyle(
                  color: selected ? Colors.white : AppTheme.ink,
                  fontSize: 13,
                ),
                checkmarkColor: Colors.white,
                onSelected: (val) {
                  setState(() {
                    if (val) {
                      _selectedMakes.add(brand);
                    } else {
                      _selectedMakes.remove(brand);
                    }
                  });
                },
              );
            }).toList(),
          ),
          const SizedBox(height: 20),

          // Body Types
          _chipGroupLabel('Body Types'),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: AppConstants.bodyTypes.map((type) {
              final selected = _selectedBodyTypes.contains(type);
              return FilterChip(
                label: Text(type),
                selected: selected,
                selectedColor: AppTheme.ink,
                labelStyle: TextStyle(
                  color: selected ? Colors.white : AppTheme.ink,
                  fontSize: 13,
                ),
                checkmarkColor: Colors.white,
                onSelected: (val) {
                  setState(() {
                    if (val) {
                      _selectedBodyTypes.add(type);
                    } else {
                      _selectedBodyTypes.remove(type);
                    }
                  });
                },
              );
            }).toList(),
          ),
          const SizedBox(height: 20),

          // Fuel Types
          _chipGroupLabel('Fuel Types'),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: AppConstants.fuelTypes.map((fuel) {
              final selected = _selectedFuelTypes.contains(fuel);
              return FilterChip(
                label: Text(fuel),
                selected: selected,
                selectedColor: AppTheme.ink,
                labelStyle: TextStyle(
                  color: selected ? Colors.white : AppTheme.ink,
                  fontSize: 13,
                ),
                checkmarkColor: Colors.white,
                onSelected: (val) {
                  setState(() {
                    if (val) {
                      _selectedFuelTypes.add(fuel);
                    } else {
                      _selectedFuelTypes.remove(fuel);
                    }
                  });
                },
              );
            }).toList(),
          ),
          const SizedBox(height: 20),

          // Transmission
          _chipGroupLabel('Transmission'),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: ['Any', 'Automatic', 'Manual'].map((t) {
              return ChoiceChip(
                label: Text(t),
                selected: _transmission == t,
                selectedColor: AppTheme.ink,
                labelStyle: TextStyle(
                  color: _transmission == t ? Colors.white : AppTheme.ink,
                  fontSize: 13,
                ),
                onSelected: (val) {
                  if (val) setState(() => _transmission = t);
                },
              );
            }).toList(),
          ),
          const SizedBox(height: 20),

          // Max Mileage
          _textField(
            'Max Mileage (km)',
            _maxMileageController,
            keyboardType: TextInputType.number,
          ),
          const SizedBox(height: 12),

          // Year range
          Text(
            'Year Range',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppTheme.gray500,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextFormField(
                  controller: _minYearController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(hintText: 'Min Year'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextFormField(
                  controller: _maxYearController,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(hintText: 'Max Year'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          _saveButton('Save Preferences', _savingPrefs, _savePreferences),

          const SizedBox(height: 32),
          const Divider(),
          const SizedBox(height: 16),

          // ---- Section 3: Notifications ----
          _sectionHeader('Notifications'),
          const SizedBox(height: 12),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text(
              'New listings matching preferences',
              style: TextStyle(fontSize: 14),
            ),
            value: _notifyNewListings,
            activeColor: AppTheme.ink,
            onChanged: (v) => setState(() => _notifyNewListings = v),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text(
              'Price drops on favorites',
              style: TextStyle(fontSize: 14),
            ),
            value: _notifyPriceDrops,
            activeColor: AppTheme.ink,
            onChanged: (v) => setState(() => _notifyPriceDrops = v),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text(
              'Weekly market digest',
              style: TextStyle(fontSize: 14),
            ),
            value: _notifyWeeklyDigest,
            activeColor: AppTheme.ink,
            onChanged: (v) => setState(() => _notifyWeeklyDigest = v),
          ),
          const SizedBox(height: 16),
          _saveButton(
            'Save Notifications',
            _savingNotifications,
            _saveNotifications,
          ),

          const SizedBox(height: 48),
        ],
      ),
    );
  }

  // ---- Helper widgets ----

  Widget _sectionHeader(String title) {
    return Text(
      title,
      style: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w700,
        color: AppTheme.ink,
      ),
    );
  }

  Widget _chipGroupLabel(String label) {
    return Text(
      label,
      style: TextStyle(
        fontSize: 13,
        fontWeight: FontWeight.w600,
        color: AppTheme.gray500,
      ),
    );
  }

  Widget _textField(
    String label,
    TextEditingController controller, {
    bool readOnly = false,
    TextInputType keyboardType = TextInputType.text,
  }) {
    return TextFormField(
      controller: controller,
      readOnly: readOnly,
      keyboardType: keyboardType,
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: AppTheme.gray500, fontSize: 14),
        filled: readOnly,
        fillColor: readOnly ? AppTheme.gray100 : null,
      ),
    );
  }

  Widget _dropdownField<T>({
    required String label,
    required T value,
    required List<DropdownMenuItem<T>> items,
    required ValueChanged<T?> onChanged,
  }) {
    return InputDecorator(
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: AppTheme.gray500, fontSize: 14),
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<T>(
          value: value,
          isExpanded: true,
          items: items,
          onChanged: onChanged,
        ),
      ),
    );
  }

  Widget _saveButton(String label, bool isLoading, VoidCallback onPressed) {
    return SizedBox(
      height: 48,
      child: ElevatedButton(
        onPressed: isLoading ? null : onPressed,
        child: isLoading
            ? const SizedBox(
                height: 20,
                width: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : Text(label),
      ),
    );
  }
}
