import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_da.dart';
import 'app_localizations_de.dart';
import 'app_localizations_en.dart';
import 'app_localizations_et.dart';
import 'app_localizations_fi.dart';
import 'app_localizations_fr.dart';
import 'app_localizations_lt.dart';
import 'app_localizations_lv.dart';
import 'app_localizations_nl.dart';
import 'app_localizations_no.dart';
import 'app_localizations_pl.dart';
import 'app_localizations_sv.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of L10n
/// returned by `L10n.of(context)`.
///
/// Applications need to include `L10n.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: L10n.localizationsDelegates,
///   supportedLocales: L10n.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the L10n.supportedLocales
/// property.
abstract class L10n {
  L10n(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static L10n? of(BuildContext context) {
    return Localizations.of<L10n>(context, L10n);
  }

  static const LocalizationsDelegate<L10n> delegate = _L10nDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('da'),
    Locale('de'),
    Locale('en'),
    Locale('et'),
    Locale('fi'),
    Locale('fr'),
    Locale('lt'),
    Locale('lv'),
    Locale('nl'),
    Locale('no'),
    Locale('pl'),
    Locale('sv'),
  ];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'Kenri.ai'**
  String get appTitle;

  /// No description provided for @heroTitle.
  ///
  /// In en, this message translates to:
  /// **'Your AI Car Advisor.'**
  String get heroTitle;

  /// No description provided for @heroSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Search, compare, and value premium cars across Europe.'**
  String get heroSubtitle;

  /// No description provided for @signIn.
  ///
  /// In en, this message translates to:
  /// **'Sign In'**
  String get signIn;

  /// No description provided for @signOut.
  ///
  /// In en, this message translates to:
  /// **'Sign Out'**
  String get signOut;

  /// No description provided for @register.
  ///
  /// In en, this message translates to:
  /// **'Register'**
  String get register;

  /// No description provided for @createAccount.
  ///
  /// In en, this message translates to:
  /// **'Create Account'**
  String get createAccount;

  /// No description provided for @forgotPassword.
  ///
  /// In en, this message translates to:
  /// **'Forgot password?'**
  String get forgotPassword;

  /// No description provided for @email.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get email;

  /// No description provided for @password.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get password;

  /// No description provided for @name.
  ///
  /// In en, this message translates to:
  /// **'Name'**
  String get name;

  /// No description provided for @or.
  ///
  /// In en, this message translates to:
  /// **'or'**
  String get or;

  /// No description provided for @signInWithGoogle.
  ///
  /// In en, this message translates to:
  /// **'Sign in with Google'**
  String get signInWithGoogle;

  /// No description provided for @dontHaveAccount.
  ///
  /// In en, this message translates to:
  /// **'Don\'t have an account?'**
  String get dontHaveAccount;

  /// No description provided for @alreadyHaveAccount.
  ///
  /// In en, this message translates to:
  /// **'Already have an account?'**
  String get alreadyHaveAccount;

  /// No description provided for @sendResetLink.
  ///
  /// In en, this message translates to:
  /// **'Send Reset Link'**
  String get sendResetLink;

  /// No description provided for @backToSignIn.
  ///
  /// In en, this message translates to:
  /// **'Back to sign in'**
  String get backToSignIn;

  /// No description provided for @newChat.
  ///
  /// In en, this message translates to:
  /// **'New Chat'**
  String get newChat;

  /// No description provided for @chatPlaceholder.
  ///
  /// In en, this message translates to:
  /// **'Search for a car, compare models, or get a valuation...'**
  String get chatPlaceholder;

  /// No description provided for @chatWelcomeTitle.
  ///
  /// In en, this message translates to:
  /// **'Kenri.ai · Personal Advisor'**
  String get chatWelcomeTitle;

  /// No description provided for @chatWelcomeBody.
  ///
  /// In en, this message translates to:
  /// **'Ask about car models, market trends, valuations, or get buying advice.'**
  String get chatWelcomeBody;

  /// No description provided for @thinking.
  ///
  /// In en, this message translates to:
  /// **'Thinking'**
  String get thinking;

  /// No description provided for @calling.
  ///
  /// In en, this message translates to:
  /// **'Calling'**
  String get calling;

  /// No description provided for @done.
  ///
  /// In en, this message translates to:
  /// **'Done'**
  String get done;

  /// No description provided for @results.
  ///
  /// In en, this message translates to:
  /// **'Results'**
  String get results;

  /// No description provided for @share.
  ///
  /// In en, this message translates to:
  /// **'Share'**
  String get share;

  /// No description provided for @copy.
  ///
  /// In en, this message translates to:
  /// **'Copy'**
  String get copy;

  /// No description provided for @copied.
  ///
  /// In en, this message translates to:
  /// **'Copied!'**
  String get copied;

  /// No description provided for @favorites.
  ///
  /// In en, this message translates to:
  /// **'Favorites'**
  String get favorites;

  /// No description provided for @noFavorites.
  ///
  /// In en, this message translates to:
  /// **'No favorites yet. Use the heart button on listings to save them.'**
  String get noFavorites;

  /// No description provided for @savedSearches.
  ///
  /// In en, this message translates to:
  /// **'Saved Searches'**
  String get savedSearches;

  /// No description provided for @noSavedSearches.
  ///
  /// In en, this message translates to:
  /// **'No saved searches yet.'**
  String get noSavedSearches;

  /// No description provided for @myGarage.
  ///
  /// In en, this message translates to:
  /// **'My Garage'**
  String get myGarage;

  /// No description provided for @noGarageCars.
  ///
  /// In en, this message translates to:
  /// **'No cars in your garage yet.'**
  String get noGarageCars;

  /// No description provided for @addCar.
  ///
  /// In en, this message translates to:
  /// **'Add Car'**
  String get addCar;

  /// No description provided for @marketMap.
  ///
  /// In en, this message translates to:
  /// **'Market Map'**
  String get marketMap;

  /// No description provided for @overview.
  ///
  /// In en, this message translates to:
  /// **'Overview'**
  String get overview;

  /// No description provided for @valueMap.
  ///
  /// In en, this message translates to:
  /// **'Value Map'**
  String get valueMap;

  /// No description provided for @priceIndex.
  ///
  /// In en, this message translates to:
  /// **'Price Index'**
  String get priceIndex;

  /// No description provided for @analytics.
  ///
  /// In en, this message translates to:
  /// **'Analytics'**
  String get analytics;

  /// No description provided for @textToSql.
  ///
  /// In en, this message translates to:
  /// **'Text to SQL + Charts'**
  String get textToSql;

  /// No description provided for @runQuery.
  ///
  /// In en, this message translates to:
  /// **'Run'**
  String get runQuery;

  /// No description provided for @profile.
  ///
  /// In en, this message translates to:
  /// **'Profile & Preferences'**
  String get profile;

  /// No description provided for @account.
  ///
  /// In en, this message translates to:
  /// **'Account'**
  String get account;

  /// No description provided for @searchPreferences.
  ///
  /// In en, this message translates to:
  /// **'Search Preferences'**
  String get searchPreferences;

  /// No description provided for @notifications.
  ///
  /// In en, this message translates to:
  /// **'Notifications'**
  String get notifications;

  /// No description provided for @save.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get save;

  /// No description provided for @saved.
  ///
  /// In en, this message translates to:
  /// **'Saved!'**
  String get saved;

  /// No description provided for @delete.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get delete;

  /// No description provided for @cancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get cancel;

  /// No description provided for @confirm.
  ///
  /// In en, this message translates to:
  /// **'Confirm'**
  String get confirm;

  /// No description provided for @error.
  ///
  /// In en, this message translates to:
  /// **'Error'**
  String get error;

  /// No description provided for @retry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get retry;

  /// No description provided for @loading.
  ///
  /// In en, this message translates to:
  /// **'Loading...'**
  String get loading;

  /// No description provided for @noData.
  ///
  /// In en, this message translates to:
  /// **'No data available'**
  String get noData;

  /// No description provided for @about.
  ///
  /// In en, this message translates to:
  /// **'About'**
  String get about;

  /// No description provided for @contact.
  ///
  /// In en, this message translates to:
  /// **'Contact Us'**
  String get contact;

  /// No description provided for @sendMessage.
  ///
  /// In en, this message translates to:
  /// **'Send Message'**
  String get sendMessage;

  /// No description provided for @exploreMarket.
  ///
  /// In en, this message translates to:
  /// **'Explore Market'**
  String get exploreMarket;

  /// No description provided for @listings.
  ///
  /// In en, this message translates to:
  /// **'Listings'**
  String get listings;

  /// No description provided for @brands.
  ///
  /// In en, this message translates to:
  /// **'Brands'**
  String get brands;

  /// No description provided for @countries.
  ///
  /// In en, this message translates to:
  /// **'Countries'**
  String get countries;

  /// No description provided for @sources.
  ///
  /// In en, this message translates to:
  /// **'Sources'**
  String get sources;

  /// No description provided for @budgetRange.
  ///
  /// In en, this message translates to:
  /// **'Budget Range (EUR)'**
  String get budgetRange;

  /// No description provided for @preferredMakes.
  ///
  /// In en, this message translates to:
  /// **'Preferred Makes'**
  String get preferredMakes;

  /// No description provided for @bodyTypes.
  ///
  /// In en, this message translates to:
  /// **'Body Types'**
  String get bodyTypes;

  /// No description provided for @fuelTypes.
  ///
  /// In en, this message translates to:
  /// **'Fuel Types'**
  String get fuelTypes;

  /// No description provided for @transmission.
  ///
  /// In en, this message translates to:
  /// **'Transmission'**
  String get transmission;

  /// No description provided for @maxMileage.
  ///
  /// In en, this message translates to:
  /// **'Max Mileage'**
  String get maxMileage;

  /// No description provided for @yearRange.
  ///
  /// In en, this message translates to:
  /// **'Year Range'**
  String get yearRange;

  /// No description provided for @newListingsNotify.
  ///
  /// In en, this message translates to:
  /// **'New listings matching my preferences'**
  String get newListingsNotify;

  /// No description provided for @priceDropsNotify.
  ///
  /// In en, this message translates to:
  /// **'Price drops on my favorites'**
  String get priceDropsNotify;

  /// No description provided for @weeklyDigestNotify.
  ///
  /// In en, this message translates to:
  /// **'Weekly market digest'**
  String get weeklyDigestNotify;

  /// No description provided for @viewTco.
  ///
  /// In en, this message translates to:
  /// **'View TCO Breakdown'**
  String get viewTco;

  /// No description provided for @totalCostOfOwnership.
  ///
  /// In en, this message translates to:
  /// **'Total Cost of Ownership'**
  String get totalCostOfOwnership;

  /// No description provided for @fuelEnergy.
  ///
  /// In en, this message translates to:
  /// **'Fuel/Energy'**
  String get fuelEnergy;

  /// No description provided for @insurance.
  ///
  /// In en, this message translates to:
  /// **'Insurance'**
  String get insurance;

  /// No description provided for @maintenance.
  ///
  /// In en, this message translates to:
  /// **'Maintenance'**
  String get maintenance;

  /// No description provided for @depreciation.
  ///
  /// In en, this message translates to:
  /// **'Depreciation'**
  String get depreciation;

  /// No description provided for @totalAnnual.
  ///
  /// In en, this message translates to:
  /// **'Total Annual'**
  String get totalAnnual;

  /// No description provided for @totalMonthly.
  ///
  /// In en, this message translates to:
  /// **'Total Monthly'**
  String get totalMonthly;

  /// No description provided for @costPerKm.
  ///
  /// In en, this message translates to:
  /// **'Cost per km'**
  String get costPerKm;

  /// No description provided for @marketValue.
  ///
  /// In en, this message translates to:
  /// **'Market Value'**
  String get marketValue;

  /// No description provided for @purchasePrice.
  ///
  /// In en, this message translates to:
  /// **'Purchase Price'**
  String get purchasePrice;

  /// No description provided for @comparables.
  ///
  /// In en, this message translates to:
  /// **'comparables'**
  String get comparables;

  /// No description provided for @allCountries.
  ///
  /// In en, this message translates to:
  /// **'All Countries'**
  String get allCountries;

  /// No description provided for @allBrands.
  ///
  /// In en, this message translates to:
  /// **'All Brands'**
  String get allBrands;

  /// No description provided for @allFuels.
  ///
  /// In en, this message translates to:
  /// **'All Fuels'**
  String get allFuels;
}

class _L10nDelegate extends LocalizationsDelegate<L10n> {
  const _L10nDelegate();

  @override
  Future<L10n> load(Locale locale) {
    return SynchronousFuture<L10n>(lookupL10n(locale));
  }

  @override
  bool isSupported(Locale locale) => <String>[
    'da',
    'de',
    'en',
    'et',
    'fi',
    'fr',
    'lt',
    'lv',
    'nl',
    'no',
    'pl',
    'sv',
  ].contains(locale.languageCode);

  @override
  bool shouldReload(_L10nDelegate old) => false;
}

L10n lookupL10n(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'da':
      return L10nDa();
    case 'de':
      return L10nDe();
    case 'en':
      return L10nEn();
    case 'et':
      return L10nEt();
    case 'fi':
      return L10nFi();
    case 'fr':
      return L10nFr();
    case 'lt':
      return L10nLt();
    case 'lv':
      return L10nLv();
    case 'nl':
      return L10nNl();
    case 'no':
      return L10nNo();
    case 'pl':
      return L10nPl();
    case 'sv':
      return L10nSv();
  }

  throw FlutterError(
    'L10n.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
