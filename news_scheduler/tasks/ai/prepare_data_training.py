#!/usr/bin/env python3
"""
Feature Preparation for ML Prediction
Prepares features exactly as used in training to ensure consistency
Matches the feature engineering from train_ml_improvement/prepare_data_training/
"""

import pandas as pd
import numpy as np
import re
import time
import warnings
import numbers
from datetime import datetime
from typing import Dict, Optional
from textblob import TextBlob
import yfinance as yf

warnings.filterwarnings('ignore')

def get_market_cap_category(market_cap_usd):
    """
    Categorize market cap based on USD value

    Category	Market-cap range (US$)
    Mega-cap	â‰¥ $200 billion
    Large-cap	$10 billion â€“ $200 billion
    Mid-cap	$2 billion â€“ $10 billion
    Small-cap	$250 million â€“ $2 billion
    Micro-cap	< $250 million
    Nano-cap	< $50 million
    """
    if pd.isna(market_cap_usd) or market_cap_usd is None:
        return 'unknown'

    market_cap_usd = float(market_cap_usd)

    if market_cap_usd >= 200_000_000_000:  # $200 billion
        return 'mega_cap'
    elif market_cap_usd >= 10_000_000_000:  # $10 billion
        return 'large_cap'
    elif market_cap_usd >= 2_000_000_000:  # $2 billion
        return 'mid_cap'
    elif market_cap_usd >= 250_000_000:  # $250 million
        return 'small_cap'
    elif market_cap_usd >= 50_000_000:  # $50 million
        return 'micro_cap'
    else:
        return 'nano_cap'

# Cache for market cap data
_market_cap_cache = {}

def fetch_market_cap_yfinance(ticker):
    """Fetch market cap using yfinance with caching"""
    if pd.isna(ticker) or not ticker:
        return None, 'unknown'

    # Check cache first
    if ticker in _market_cap_cache:
        return _market_cap_cache[ticker]

    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info

        market_cap = info.get('marketCap')
        if market_cap:
            market_cap_category = get_market_cap_category(market_cap)
            result = (float(market_cap), market_cap_category)
            _market_cap_cache[ticker] = result
            return result
        else:
            result = (None, 'unknown')
            _market_cap_cache[ticker] = result
            return result

    except Exception as e:
        result = (None, 'unknown')
        _market_cap_cache[ticker] = result
        return result

def get_market_context_features(date: str) -> Dict:
    """
    Get market context features for a specific date

    Args:
        date: Date in YYYY-MM-DD format or datetime

    Returns:
        Dict of market context features
    """
    try:
        if isinstance(date, str):
            target_date = pd.to_datetime(date)
        else:
            target_date = date

        if pd.isna(target_date):
            return {}

        features = {}

        # Time-based features
        features['hour'] = target_date.hour
        features['day_of_week'] = target_date.dayofweek
        features['day_of_month'] = target_date.day
        features['month'] = target_date.month
        features['quarter'] = target_date.quarter
        features['year'] = target_date.year
        features['day_of_year'] = target_date.dayofyear
        features['week_of_year'] = target_date.isocalendar()[1]

        # Market hours indicators
        features['is_market_hours'] = 1 if 9 <= target_date.hour <= 16 else 0
        features['is_pre_market'] = 1 if 4 <= target_date.hour < 9 else 0
        features['is_after_hours'] = 1 if 16 < target_date.hour <= 20 else 0
        features['is_weekend'] = 1 if target_date.dayofweek >= 5 else 0

        # Seasonal indicators
        features['is_month_end'] = 1 if target_date.day >= 28 else 0
        features['is_quarter_end'] = 1 if target_date.month in [3, 6, 9, 12] and target_date.day >= 28 else 0
        features['is_year_end'] = 1 if target_date.month == 12 and target_date.day >= 28 else 0

        # Earnings season indicators (approximate)
        features['is_earnings_season'] = 1 if target_date.month in [1, 4, 7, 10] and 1 <= target_date.day <= 15 else 0

        # Holiday indicators (simplified)
        features['is_holiday_period'] = 1 if (
            (target_date.month == 12 and target_date.day >= 20) or
            (target_date.month == 1 and target_date.day <= 5) or
            (target_date.month == 7 and target_date.day == 4)
        ) else 0

        # Volatility periods (historical patterns)
        features['is_high_volatility_period'] = 1 if target_date.month in [10, 11] else 0

        return features

    except Exception as e:
        return {}

def get_content_analysis_features(title: str, content: str) -> Dict:
    """
    Get content analysis features

    Args:
        title: News title
        content: News content

    Returns:
        Dict of content analysis features
    """
    try:
        features = {}

        # Text length features
        features['title_length'] = len(title) if title else 0
        features['content_length'] = len(content) if content else 0
        features['title_word_count'] = len(title.split()) if title else 0
        features['content_word_count'] = len(content.split()) if content else 0
        features['avg_word_length'] = np.mean([len(word) for word in (title + ' ' + content).split()]) if title or content else 0

        # Sentiment analysis
        if title or content:
            text = (title + ' ' + content).strip()
            if text:
                blob = TextBlob(text)
                features['sentiment_polarity'] = blob.sentiment.polarity
                features['sentiment_subjectivity'] = blob.sentiment.subjectivity
            else:
                features['sentiment_polarity'] = 0.0
                features['sentiment_subjectivity'] = 0.0
        else:
            features['sentiment_polarity'] = 0.0
            features['sentiment_subjectivity'] = 0.0

        # Keyword analysis
        text = (title + ' ' + content).lower() if title or content else ''

        # Financial keywords
        financial_keywords = ['earnings', 'revenue', 'profit', 'loss', 'growth', 'decline', 'increase', 'decrease',
                            'quarterly', 'annual', 'forecast', 'guidance', 'dividend', 'stock', 'share', 'market']
        features['financial_keyword_count'] = sum(1 for keyword in financial_keywords if keyword in text)

        # Market keywords
        market_keywords = ['bull', 'bear', 'rally', 'crash', 'volatility', 'trading', 'investor', 'analyst',
                          'upgrade', 'downgrade', 'target', 'price', 'valuation']
        features['market_keyword_count'] = sum(1 for keyword in market_keywords if keyword in text)

        # Urgency keywords
        urgency_keywords = ['urgent', 'breaking', 'immediate', 'critical', 'important', 'significant', 'major',
                           'unexpected', 'surprise', 'shock']
        features['urgency_keyword_count'] = sum(1 for keyword in urgency_keywords if keyword in text)

        # Regulatory keywords
        regulatory_keywords = ['sec', 'fda', 'approval', 'regulation', 'compliance', 'investigation', 'lawsuit',
                              'settlement', 'fine', 'penalty']
        features['regulatory_keyword_count'] = sum(1 for keyword in regulatory_keywords if keyword in text)

        # Size indicators
        size_keywords = ['billion', 'million', 'trillion', 'massive', 'huge', 'large', 'small', 'tiny']
        features['size_keyword_count'] = sum(1 for keyword in size_keywords if keyword in text)

        # Punctuation analysis
        features['exclamation_count'] = text.count('!')
        features['question_count'] = text.count('?')
        features['period_count'] = text.count('.')
        features['comma_count'] = text.count(',')

        # Number analysis
        features['has_numbers'] = 1 if re.search(r'\d', text) else 0
        features['has_percentages'] = 1 if '%' in text else 0
        features['has_quotes'] = 1 if '"' in text or "'" in text else 0

        # Readability features (simplified)
        sentences = re.split(r'[.!?]+', text)
        words = text.split()
        features['avg_sentence_length'] = len(words) / len(sentences) if sentences and words else 0
        features['sentence_count'] = len(sentences)

        return features

    except Exception as e:
        return {}

def prepare_all_features_for_prediction(row: pd.Series) -> Dict:
    """
    Prepare all features for prediction exactly as used in training

    Args:
        row: DataFrame row with news data

    Returns:
        Dict of all features ready for prediction
    """
    features = {}

    # 1. Market context features
    published_date = row.get('published_date')
    market_context = get_market_context_features(published_date)
    features.update(market_context)

    # 2. Content analysis features
    title = row.get('title_en') or row.get('title', '')
    content = row.get('content_en') or row.get('content', '')
    content_features = get_content_analysis_features(title, content)
    features.update(content_features)

    # 3. Market cap features
    yf_ticker = row.get('yf_ticker')
    market_cap_usd, market_cap_category = fetch_market_cap_yfinance(yf_ticker)
    features['market_cap_usd'] = market_cap_usd if market_cap_usd else 0.0
    features['market_cap_category'] = market_cap_category

    # 4. Categorical features (keep as-is, will be encoded/hashed in prepare_features_for_prediction)
    features['yf_ticker'] = row.get('yf_ticker', '')
    features['market_status'] = row.get('market_status', '')
    features['event_standardized'] = row.get('event_standardized', '')
    features['company'] = row.get('company', '')
    features['publisher'] = row.get('publisher', '')
    features['industry'] = row.get('industry', '')

    # 5. Additional fields that might be in training data
    features['exchange'] = row.get('exchange', '')
    features['etf_ticker'] = row.get('etf_ticker', '')

    return features

def add_all_features_to_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all features to dataframe for prediction

    Args:
        df: DataFrame with news data

    Returns:
        DataFrame with all features added
    """
    df_enhanced = df.copy()

    # Process each row to add features
    for idx, row in df_enhanced.iterrows():
        # Get all features for this row
        all_features = prepare_all_features_for_prediction(row)

        # Add features to dataframe
        for feature_name, feature_value in all_features.items():
            if feature_name not in df_enhanced.columns:
                # Initialize column with appropriate default
                if isinstance(feature_value, numbers.Number):
                    # Use a floating-point column because engineered numeric
                    # features can mix whole numbers and decimal values.
                    df_enhanced[feature_name] = 0.0
                else:
                    df_enhanced[feature_name] = ''

            df_enhanced.at[idx, feature_name] = feature_value

        # Small delay to avoid rate limiting for market cap
        if idx % 100 == 0 and idx > 0:
            time.sleep(0.1)

    return df_enhanced
