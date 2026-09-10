"""
Prediction function for news items
Uses models from model_tracking table via utils/db/model_db_util.py
Prepares features using prepare_data_training.py to match training exactly
"""
import pandas as pd
import numpy as np
import unicodedata
import re
import warnings
import os
import sys
from sklearn.exceptions import InconsistentVersionWarning

from utils.db.model_db_util import get_best_model_id_from_tracking, load_model_components_from_tracking
from utils.logging.log_util import get_logger
from tasks.ai.prepare_data_training import add_all_features_to_dataframe

logger = get_logger(__name__)

# Import event standardization function
def comprehensive_event_standardization(event):
    """
    Comprehensive event name standardization function from standardize_events.py
    This ensures event names match what's in the model_tracking table
    """
    if pd.isna(event) or event is None:
        return 'no_event'

    event_str = str(event).strip()

    if not event_str:
        return 'no_event'

    event_lower = event_str.lower()

    # Define exact name mappings - same as standardize_events.py
    exact_mappings = {
        # Earnings-related events
        'earnings_releases_and_operating_results': 'earnings',
        'earnings': 'earnings',
        'earning': 'earnings',

        # Financial results
        'financial_results': 'financial_results',

        # Share buyback events
        'changes_in_companys_own_shares': 'share_buyback',
        'share buyback': 'share_buyback',
        'share buybacks': 'share_buyback',

        # Share issue events
        'shares_issue': 'share_issue',
        'share_capital_increase': 'share_issue',
        'rights_issue': 'share_issue',
        'bonds_issue': 'share_issue',

        # Merger and acquisition events
        'mergers_acquisitions': 'merger_acquisition',
        'acquisition': 'merger_acquisition',

        # Clinical study events
        'clinical_study': 'clinical_study',
        'orphan_drug_designation': 'clinical_study',

        # Regulatory events
        'regulatory_filings': 'regulatory',
        'company_regulatory_filings': 'regulatory',

        # Management changes
        'management_changes': 'management_changes',
        'managing_changes': 'management_changes',
        'managemen_changes': 'management_changes',

        # Corporate actions
        'corporate_action': 'corporate_action',
        'dividend_reports_and_estimates': 'corporate_action',
        'ex_dividend_date': 'corporate_action',

        # Conference/webinar events
        'conference_call_webinar': 'conference',
        'investor_day': 'conference',
        'investor_update': 'conference',

        # Annual events
        'annual_general_meeting': 'annual_events',
        'annual_report': 'annual_events',
        'annual_meetings_shareholder_rights': 'annual_events',
        'extraordinary_general_meeting': 'annual_events',
        'extraordinary_general_meetings': 'annual_events',
        'extraordinary_meeting': 'annual_events',
        'special_general_meeting': 'annual_events',
        'special_shareholders_meeting': 'annual_events',

        # Legal issues
        'law_legal_issues': 'legal_issues',
        'insurance_settlement': 'legal_issues',
        'insurance_claim_settlement': 'legal_issues',

        # Product announcements
        'product_services_announcement': 'product_announcement',
        'production_services_announcement': 'product_announcement',

        # Press releases (IMPORTANT: plural to singular)
        'press_releases': 'press_release',
        'company_announcement': 'press_release',

        # Business contracts
        'business_contracts': 'business_contract',
        'contract': 'business_contract',
        'agreement': 'business_contract',
        'partnership': 'partnership',
        'partnerships': 'partnership',
        'joint_venture': 'joint_venture',
        'licensing_agreements': 'licensing_agreements',

        # Financing events
        'financing_agreements': 'financing',
        'credit_rating': 'financing',
        'credit_rating_update': 'financing',
        'credit_ratings': 'financing',
        'credit_rating_changes': 'financing',
        'credit_rating_updates': 'financing',
        'rating_agency_actions': 'financing',
        'debt_restructuring': 'financing',

        # Bond events
        'bond_fixing': 'bond_event',
        'bonds_fixing': 'bond_event',
        'green_bond': 'bond_event',
        'green_bond_issuance': 'bond_event',
        'sustainability-linked_bonds': 'bond_event',

        # Voting rights
        'voting_rights': 'voting_rights',

        # Major shareholder events
        'major_shareholder_announcements': 'shareholder_event',
        'insider_transactions': 'shareholder_event',
        'insider_trading': 'shareholder_event',
        'managers_transactions': 'shareholder_event',
        "managers'_transactions": 'shareholder_event',
        'manager_transactions': 'shareholder_event',
        'manager_transaction': 'shareholder_event',
        'managerial_transactions': 'shareholder_event',
        'management_transactions': 'shareholder_event',
        'PDMR_trading_notification': 'shareholder_event',
        'director_pdmr_holding': 'shareholder_event',

        # Trading information
        'trading_information': 'trading_info',
        'market_making_contracts': 'trading_info',
        'liquidity_contract': 'trading_info',
        'liquidity_contracts': 'trading_info',
        'liquidity_agreement': 'trading_info',
        'liquidity_agreements': 'trading_info',
        'liquidity_provider_appointment': 'trading_info',

        # Interim reports
        'interim_information': 'interim_report',
        'monthly_statement': 'interim_report',

        # Employee/shareholder programs
        'employee_share_ownership': 'employee_programs',
        'employee_shareholding': 'employee_programs',
        'employee_share_savings_plan': 'employee_programs',
        'employee_share_purchase_programme': 'employee_programs',
        'employee_share_purchase_programs': 'employee_programs',
        'employee_stock_ownership': 'employee_programs',
        'stock_option_program': 'employee_programs',
        'long-term_incentive_plan': 'employee_programs',
        'incentive_programme': 'employee_programs',

        # Restructuring events
        'restructuring': 'restructuring',
        'strategic_restructuring': 'restructuring',
        'restructuring_proceedings': 'restructuring',
        'restructuring_initiatives': 'restructuring',
        'recapitalization': 'restructuring',
        'divestment': 'restructuring',
        'divestitures': 'restructuring',
        'divestiture': 'restructuring',
        'strategic_review': 'restructuring',
        'strategy_adjustment': 'restructuring',
        'strategy_development': 'restructuring',
        'strategic_plan': 'restructuring',
        'strategic_plans': 'restructuring',
        'strategic_targets': 'restructuring',

        # Bankruptcy/Delisting events
        'bankruptcy': 'corporate_crisis',
        'delisting': 'corporate_crisis',
        'delisting_notice': 'corporate_crisis',

        # Patent/IP events
        'patents': 'intellectual_property',
        'Patents': 'intellectual_property',
        'trademark': 'intellectual_property',
        'trademarks': 'intellectual_property',
        'certification': 'intellectual_property',

        # Research/Analysis events
        'research_analysis_and_reports': 'research_analysis',
        'market_research_reports': 'research_analysis',
        'analyst_coverage': 'research_analysis',
        'feature_article': 'research_analysis',
        'advisory': 'research_analysis',

        # Government/Regulatory news
        'government_news': 'government_news',
        'mandatory_notifications': 'government_news',
        'transparency_notifications': 'government_news',
        'transparency_notification': 'government_news',

        # ESG/Sustainability events
        'environmental_social_governance': 'esg_sustainability',
        'sustainability': 'esg_sustainability',

        # Capital/Investment events
        'capital_investment': 'capital_investment',
        'geographic_expansion': 'capital_investment',
        'real_estate_development': 'capital_investment',
        'exploration': 'capital_investment',
        'drilling_results': 'capital_investment',
        'energy': 'capital_investment',

        # IPO/Listing events
        'initial_public_offerings': 'ipo_listing',
        'prospectus_announcement': 'ipo_listing',
        'exchange_announcement': 'ipo_listing',

        # Warrants/Certificates
        'warrants_and_certificates': 'warrants_certificates',

        # Fund/Investment vehicle events
        'fund_data_announcement': 'fund_events',
        'observation_status': 'fund_events',

        # Trade show/Events
        'trade_show': 'trade_events',
        'contests_awards': 'trade_events',
        'milestone_achievement': 'trade_events',

        # Calendar/Financial calendar
        'financial_calendar': 'financial_calendar',

        # Changes in share capital
        'changes_in_share_capital_and_votes': 'share_capital_changes',

        # Nomination/Governance
        'nomination_committee': 'governance',
        'shareholders_nomination_board': 'governance',

        # Management statements
        'management_statements': 'management_statements',
        'letter_to_shareholders': 'management_statements',
        'operational_performance': 'management_statements',
        'operational_update': 'management_statements',
        'fleet_status_report': 'management_statements',
        'activity_report': 'management_statements',

        # Profit warnings
        'profit_warning': 'profit_warning',
        'negative_profit_warning': 'profit_warning',

        # Technical issues
        'technical_issue': 'technical_issue',
        'error': 'technical_issue',
        'correction': 'technical_issue',

        # Individual events
        'related_party_transaction': 'related_party_transaction',
        'investor_relations': 'investor_relations',
        'transfer': 'transfer',
        'stabilization_measures': 'stabilization',
        'stabilization': 'stabilization',
        'attachments': 'attachments',
        'attachment': 'attachments',
        'hedging': 'hedging',
        'remuneration': 'remuneration',
        'news_placeholder': 'news_placeholder',
        'news': 'news_placeholder',
        'rescheduling': 'rescheduling',
        'cost_savings': 'cost_savings',
        'reverse_stock_split': 'reverse_stock_split',
        'housing_cession': 'housing_cession',
        'transactiondirigenteen': 'transactiondirigenteen',
        'pre-release_comments': 'pre_release_comments',
        'guidance_adjustment': 'guidance_adjustment',
        'rebranding': 'rebranding',
        'settlement': 'settlement',
    }

    # Check for exact match first
    if event_str in exact_mappings:
        return exact_mappings[event_str]

    # If no exact match found, normalize: lowercase, replace spaces with underscores
    normalized = event_lower.replace(' ', '_')

    # If still no match, return normalized version (truncate if too long)
    if len(normalized) > 500:
        return normalized[:497] + "..."

    return normalized

# Global cache for loaded model components
_model_components_cache = {}

def normalize_text(text):
    """Normalize text by removing accents and non-ASCII characters - same as prediction pipeline"""
    if pd.isna(text) or text == '':
        return ''

    # Convert to string and normalize unicode
    text = str(text)
    text = unicodedata.normalize('NFKD', text)

    # Remove accents and non-ASCII characters
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')

    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text.lower()

def prepare_features_for_prediction(row, feature_columns, title_tfidf, content_tfidf):
    """
    Prepare features for prediction using the same preprocessing as training
    Matches Prediction_pipeline/prediction_pipeline.py logic

    Args:
        row: DataFrame row with news data
        feature_columns: List of feature column names from model
        title_tfidf: Fitted TF-IDF vectorizer for titles
        content_tfidf: Fitted TF-IDF vectorizer for content

    Returns:
        Prepared feature array or None if failed
    """
    try:
        # Get text - prefer English translated versions
        title_text = row.get('title_en') or row.get('title', '')
        content_text = row.get('content_en') or row.get('content', '')

        # Normalize text
        title_normalized = normalize_text(title_text)
        content_normalized = normalize_text(content_text)

        # Get TF-IDF features using the fitted vectorizers
        title_features = title_tfidf.transform([title_normalized]).toarray() if title_tfidf else np.array([])
        content_features = content_tfidf.transform([content_normalized]).toarray() if content_tfidf else np.array([])

        # Prepare base features from feature_columns
        base_features = []
        if feature_columns:
            for col in feature_columns:
                # Skip TF-IDF features, handled separately
                if col.startswith('title_tfidf_') or col.startswith('content_tfidf_'):
                    continue

                # Get value from row, default to 0 if missing
                value = row.get(col, 0)

                # Handle missing market_cap features - use 0 as default
                if col == 'market_cap_usd' and (pd.isna(value) or value == 0):
                    value = 0.0
                elif col == 'market_cap_category':
                    # Handle categorical features - same mapping as training
                    market_cap_mapping = {
                        'nano_cap': 1,
                        'micro_cap': 2,
                        'small_cap': 3,
                        'mid_cap': 4,
                        'large_cap': 5,
                        'mega_cap': 6
                    }
                    # If missing, default to 0 (unknown)
                    if pd.isna(value) or value == '' or value == 0:
                        value = 0
                    else:
                        value = market_cap_mapping.get(str(value).lower(), 0)
                elif col in ['yf_ticker', 'market_status', 'event_standardized', 'company']:
                    # Convert to numeric code (same as training)
                    # Use event if event_standardized is missing
                    if col == 'event_standardized' and (pd.isna(value) or value == ''):
                        value = row.get('event', '')
                    value = hash(str(value)) % 1000 if value else 0

                # Ensure numeric
                try:
                    value = float(value) if not pd.isna(value) else 0.0
                except (ValueError, TypeError):
                    value = 0.0

                base_features.append(value)

        # Combine base features with TF-IDF features
        all_features = np.array(base_features)
        if title_features.size > 0:
            all_features = np.concatenate([all_features, title_features.flatten()])
        if content_features.size > 0:
            all_features = np.concatenate([all_features, content_features.flatten()])

        logger.debug(f"Prepared {len(all_features)} features ({len(base_features)} base + {title_features.size if title_features.size > 0 else 0} title TF-IDF + {content_features.size if content_features.size > 0 else 0} content TF-IDF)")
        return all_features
    except Exception as e:
        logger.warning(f"Error preparing features: {e}")
        return None

def get_model_components_for_event(event_type, model_type, min_accuracy=0.5):
    """
    Get model components for event and model type
    Uses caching to avoid reloading
    """
    cache_key = f"{event_type}_{model_type}"

    if cache_key in _model_components_cache:
        logger.debug(f"Loading model components for {event_type}, {model_type} from cache")
        return _model_components_cache[cache_key]

    # Get best model_id from model_tracking
    model_id = get_best_model_id_from_tracking(event_type, model_type, min_accuracy)

    if not model_id:
        logger.debug(f"No model found for {event_type}, {model_type}")
        _model_components_cache[cache_key] = None
        return None

    # Load model components
    components = load_model_components_from_tracking(model_id)

    if components:
        _model_components_cache[cache_key] = components
        logger.info(f"Loaded {model_type} model for {event_type}: {model_id}")
    else:
        _model_components_cache[cache_key] = None

    return components

def predict(df):
    """
    Predict side and move for news items in DataFrame
    Uses models from model_tracking table - same logic as prediction pipeline
    Prepares features using prepare_data_training.py to match training exactly

    NOTE: This function only makes predictions. It does NOT:
    - Set model_id_classifier or model_id_regressor (handled in predict_all_news.py)
    - Set classifier_prob or regressor_prob (handled in predict_all_news.py)
    - Save to database or CSV (handled in predict_all_news.py)

    It only returns predictions: predicted_side and predicted_move
    """
    if df.empty:
        logger.warning("Empty DataFrame passed to predict()")
        return df

    # Step 1: Standardize events first (needed for feature preparation)
    if 'event_standardized' not in df.columns:
        logger.info("Standardizing events...")
        df['event_standardized'] = df['event'].apply(comprehensive_event_standardization)

    # Step 2: Prepare all features exactly as used in training
    # This uses prepare_data_training.py to add: market cap, text analysis, market context, etc.
    # All features match exactly what was used during model training
    logger.info("Preparing features for prediction (matching training pipeline)...")
    df = add_all_features_to_dataframe(df)
    logger.info("âœ… Features prepared (market cap, text analysis, market context, etc.)")

    # Initialize prediction columns if not present
    # NOTE: Do NOT initialize model_id or prob columns here - those are handled in predict_all_news.py
    if 'predicted_side' not in df.columns:
        df['predicted_side'] = None
    if 'predicted_move' not in df.columns:
        df['predicted_move'] = None

    # Get unique events and normalize them
    events = df['event'].dropna()
    events = events[events != ''].unique().tolist()

    if not events:
        logger.warning("No valid events found in DataFrame")
        return df

    logger.info(f"Making predictions for {len(df)} news items with events: {events}")

    # Standardize event names using comprehensive_event_standardization
    # This ensures events match what's in the model_tracking table
    event_mapping = {}
    for event in events:
        standardized = comprehensive_event_standardization(event)
        event_mapping[event] = standardized

    logger.info(f"Standardized events: {event_mapping}")

    # Load model components for each normalized event (cache them)
    event_models = {}
    for original_event, normalized_event in event_mapping.items():
        event_models[original_event] = {}

        # Get classifier model (for side prediction)
        classifier_components = get_model_components_for_event(normalized_event, 'classifier', min_accuracy=0.5)
        if classifier_components:
            event_models[original_event]['classifier'] = classifier_components
            logger.info(f"Loaded classifier for '{original_event}' (normalized: '{normalized_event}')")
        else:
            logger.debug(f"No classifier found for '{original_event}' (normalized: '{normalized_event}')")

        # Get regressor model (for move prediction)
        regressor_components = get_model_components_for_event(normalized_event, 'regressor', min_accuracy=0.0)
        if regressor_components:
            event_models[original_event]['regressor'] = regressor_components
            logger.info(f"Loaded regressor for '{original_event}' (normalized: '{normalized_event}')")
        else:
            logger.debug(f"No regressor found for '{original_event}' (normalized: '{normalized_event}')")

    # Make predictions for each row
    for idx, row in df.iterrows():
        event = row.get('event', '')
        if not event or event not in event_models:
            continue

        models = event_models[event]

        # Predict side (classification)
        if 'classifier' in models and pd.isna(row.get('predicted_side')):
            try:
                components = models['classifier']
                title_tfidf = components.get('title_tfidf')
                content_tfidf = components.get('content_tfidf')

                if not title_tfidf and not content_tfidf:
                    logger.warning(f"No TF-IDF vectorizers available for side prediction (row {idx})")
                    continue

                # Get feature columns from model components
                feature_columns = components.get('feature_columns', [])
                if isinstance(feature_columns, str):
                    # If stored as JSON string, parse it
                    import json
                    try:
                        feature_columns = json.loads(feature_columns)
                    except:
                        feature_columns = []

                # Prepare features
                features = prepare_features_for_prediction(row, feature_columns, title_tfidf, content_tfidf)
                if features is None:
                    continue

                # Scale features if scaler available
                if components.get('scaler'):
                    expected_features = components['scaler'].n_features_in_
                    if len(features) != expected_features:
                        # Pad or truncate to match expected count
                        if len(features) > expected_features:
                            features = features[:expected_features]
                            logger.debug(f"Truncated features to {len(features)}")
                        else:
                            padding = np.zeros(expected_features - len(features))
                            features = np.concatenate([features, padding])
                            logger.debug(f"Padded features to {len(features)}")

                    features_scaled = components['scaler'].transform([features])
                else:
                    features_scaled = [features]

                # Make prediction
                prediction_encoded = components['model'].predict(features_scaled)[0]

                # Get prediction confidence (probability)
                if hasattr(components['model'], 'predict_proba'):
                    proba = components['model'].predict_proba(features_scaled)[0]
                    confidence = np.max(proba)
                else:
                    confidence = 1.0

                # Decode prediction back to text label
                if components.get('encoder'):
                    prediction_decoded = components['encoder'].inverse_transform([prediction_encoded])[0]
                    # Log available classes in encoder to verify NEUTRAL support
                    if hasattr(components['encoder'], 'classes_'):
                        logger.debug(f"Encoder classes available: {components['encoder'].classes_}")
                else:
                    prediction_decoded = prediction_encoded

                df.at[idx, 'predicted_side'] = str(prediction_decoded).upper()
                logger.debug(f"Predicted side for row {idx}: {df.at[idx, 'predicted_side']} (confidence: {confidence:.2%})")

            except Exception as e:
                logger.warning(f"Error predicting side for row {idx}: {e}")

        # Predict move (regression)
        if 'regressor' in models and pd.isna(row.get('predicted_move')):
            try:
                components = models['regressor']
                title_tfidf = components.get('title_tfidf')
                content_tfidf = components.get('content_tfidf')

                if not title_tfidf and not content_tfidf:
                    logger.warning(f"No TF-IDF vectorizers available for move prediction (row {idx})")
                    continue

                # Get feature columns from model components
                feature_columns = components.get('feature_columns', [])
                if isinstance(feature_columns, str):
                    # If stored as JSON string, parse it
                    import json
                    try:
                        feature_columns = json.loads(feature_columns)
                    except:
                        feature_columns = []

                # Prepare features
                features = prepare_features_for_prediction(row, feature_columns, title_tfidf, content_tfidf)
                if features is None:
                    continue

                # Scale features if scaler available
                if components.get('scaler'):
                    expected_features = components['scaler'].n_features_in_
                    if len(features) != expected_features:
                        # Pad or truncate to match expected count
                        if len(features) > expected_features:
                            features = features[:expected_features]
                            logger.debug(f"Truncated features to {len(features)}")
                        else:
                            padding = np.zeros(expected_features - len(features))
                            features = np.concatenate([features, padding])
                            logger.debug(f"Padded features to {len(features)}")

                    features_scaled = components['scaler'].transform([features])
                else:
                    features_scaled = [features]

                # Make prediction
                predicted_move = components['model'].predict(features_scaled)[0]
                df.at[idx, 'predicted_move'] = float(predicted_move)
                logger.debug(f"Predicted move for row {idx}: {df.at[idx, 'predicted_move']:.2f}%")

            except Exception as e:
                logger.warning(f"Error predicting move for row {idx}: {e}")

    side_count = df['predicted_side'].notna().sum()
    move_count = df['predicted_move'].notna().sum()
    up_count = (df['predicted_side'] == 'UP').sum() if 'predicted_side' in df.columns else 0
    down_count = (df['predicted_side'] == 'DOWN').sum() if 'predicted_side' in df.columns else 0
    neutral_count = (df['predicted_side'] == 'NEUTRAL').sum() if 'predicted_side' in df.columns else 0
    logger.info(f"Predictions completed. Side: {side_count}/{len(df)} (UP: {up_count}, DOWN: {down_count}, NEUTRAL: {neutral_count}), Move: {move_count}/{len(df)}")

    # NOTE: Predictions are saved to database after news insertion in download_util.py
    # This ensures news_id is available

    return df

def main():
    """Main function for standalone testing"""
    from utils.db.news_db_util import get_news_df, update_news_predictions

    logger.info("Fetching news data")
    news_df = get_news_df()

    logger.info("Making predictions")
    pred_df = predict(news_df)

    logger.info("Updating news table with predictions")
    update_news_predictions(pred_df)

    logger.info("Predictions completed and news table updated.")
