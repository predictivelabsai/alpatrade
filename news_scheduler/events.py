"""Event normalization used by the trained Finespresso model registry."""
from __future__ import annotations

import re
from typing import Any

_ALIASES = {
    "earnings_releases_and_operating_results": "earnings", "earning": "earnings",
    "changes_in_companys_own_shares": "share_buyback", "share buyback": "share_buyback",
    "shares_issue": "share_issue", "share_capital_increase": "share_issue",
    "mergers_acquisitions": "merger_acquisition", "acquisition": "merger_acquisition",
    "orphan_drug_designation": "clinical_study", "regulatory_filings": "regulatory",
    "company_regulatory_filings": "regulatory", "managing_changes": "management_changes",
    "managemen_changes": "management_changes", "dividend_reports_and_estimates": "corporate_action",
    "conference_call_webinar": "conference", "investor_day": "conference",
    "annual_general_meeting": "annual_events", "annual_report": "annual_events",
    "law_legal_issues": "legal_issues", "product_services_announcement": "product_announcement",
    "production_services_announcement": "product_announcement", "press_releases": "press_release",
    "company_announcement": "press_release", "business_contracts": "business_contract",
    "financing_agreements": "financing", "credit_rating": "financing",
    "insider_transactions": "shareholder_event", "trading_information": "trading_info",
    "interim_information": "interim_report", "profit_warning": "profit_warning",
    "negative_profit_warning": "profit_warning", "initial_public_offerings": "ipo_listing",
    "environmental_social_governance": "esg_sustainability",
}


def normalize_event(value: Any) -> str:
    if value is None or not str(value).strip():
        return "no_event"
    raw = str(value).strip()
    key = re.sub(r"[\s-]+", "_", raw.lower())
    return _ALIASES.get(raw, _ALIASES.get(key, key[:500]))
