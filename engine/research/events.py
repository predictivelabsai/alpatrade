"""Canonical event normalization shared by research views and agent tools."""
from __future__ import annotations

import re

# Kept explicit: these aliases are part of the model's historical feature space.
_GROUPS = {
    "earnings": ("earnings_releases_and_operating_results", "earnings", "earning"),
    "financial_results": ("financial_results",),
    "share_buyback": ("changes_in_companys_own_shares", "share buyback", "share buybacks"),
    "share_issue": ("shares_issue", "share_capital_increase", "rights_issue", "bonds_issue"),
    "merger_acquisition": ("mergers_acquisitions", "acquisition", "acquisitions"),
    "clinical_study": ("clinical_study", "orphan_drug_designation"),
    "regulatory": ("regulatory_filings", "company_regulatory_filings"),
    "management_changes": ("management_changes", "managing_changes", "managemen_changes"),
    "corporate_action": ("corporate_action", "dividend_reports_and_estimates", "ex_dividend_date"),
    "conference": ("conference_call_webinar", "investor_day", "investor_update", "roadshow"),
    "annual_events": ("annual_general_meeting", "annual_report", "annual_meetings_shareholder_rights",
                      "extraordinary_general_meeting", "extraordinary_general_meetings",
                      "extraordinary_meeting", "special_general_meeting", "special_shareholders_meeting"),
    "legal_issues": ("law_legal_issues", "insurance_settlement", "insurance_claim_settlement",
                     "bankruptcy", "delisting", "delisting_notice"),
    "product_announcement": ("product_services_announcement", "production_services_announcement"),
    "press_release": ("press_releases", "company_announcement", "research_analysis_and_reports",
                      "market_research_reports", "analyst_coverage", "feature_article", "advisory"),
    "business_contract": ("business_contracts", "contract", "agreement"),
    "partnership": ("partnership", "partnerships"),
    "joint_venture": ("joint_venture",),
    "licensing_agreements": ("licensing_agreements",),
    "financing": ("financing_agreements", "credit_rating", "credit_rating_update", "credit_ratings",
                  "credit_rating_changes", "credit_rating_updates", "rating_agency_actions",
                  "debt_restructuring"),
    "bond_event": ("bond_fixing", "bonds_fixing", "green_bond", "green_bond_issuance",
                   "sustainability-linked_bonds"),
    "voting_rights": ("voting_rights",),
    "shareholder_event": ("major_shareholder_announcements", "insider_transactions", "insider_trading",
                          "managers_transactions", "managers'_transactions", "manager_transactions",
                          "manager_transaction", "manager's_transactions", "managerial_transactions",
                          "management_transactions", "pdmr_trading_notification",
                          "director_pdmr_holding", "managers' transactions"),
    "trading_info": ("trading_information", "market_making_contracts", "liquidity_contract",
                     "liquidity_contracts", "liquidity_agreement", "liquidity_agreements",
                     "liquidity_provider_appointment"),
    "interim_report": ("interim_information", "monthly_statement"),
    "employee_programs": ("employee_share_ownership", "employee_shareholding",
                          "employee_share_savings_plan", "employee_share_purchase_programme",
                          "employee_share_purchase_programs", "employee_stock_ownership",
                          "stock_option_program", "long-term_incentive_plan", "incentive_programme"),
    "restructuring": ("restructuring", "strategic_restructuring", "restructuring_proceedings",
                      "restructuring_initiatives", "recapitalization", "divestment", "divestitures",
                      "divestiture", "strategic_review", "strategy_adjustment", "strategy_development",
                      "strategic_plan", "strategic_plans", "strategic_targets"),
    "intellectual_property": ("patents", "trademark", "trademarks", "certification"),
    "government_news": ("government_news", "mandatory_notifications", "transparency_notifications",
                        "transparency_notification"),
    "esg_sustainability": ("environmental_social_governance", "sustainability"),
    "capital_investment": ("capital_investment", "geographic_expansion", "real_estate_development",
                           "exploration", "drilling_results", "energy"),
    "ipo_listing": ("initial_public_offerings", "prospectus_announcement", "exchange_announcement"),
    "warrants_certificates": ("warrants_and_certificates",),
    "fund_events": ("fund_data_announcement", "observation_status"),
    "trade_events": ("trade_show", "contests_awards", "milestone_achievement"),
    "financial_calendar": ("financial_calendar",),
    "share_capital_changes": ("changes_in_share_capital_and_votes",),
    "governance": ("nomination_committee", "shareholders_nomination_board"),
    "management_statements": ("management_statements", "letter_to_shareholders",
                              "operational_performance", "operational_update", "fleet_status_report",
                              "activity_report"),
    "profit_warning": ("profit_warning", "negative_profit_warning"),
    "technical_issue": ("technical_issue", "error", "correction"),
}
EVENT_ALIASES = {alias.lower(): group for group, aliases in _GROUPS.items() for alias in aliases}


def normalize_event(value: str | None) -> str:
    """Return the stable model event group, retaining unknown events."""
    raw = (value or "").strip()
    if not raw:
        return "uncategorized"
    key = raw.lower()
    if key in EVENT_ALIASES:
        return EVENT_ALIASES[key]
    return re.sub(r"[^a-z0-9]+", "_", key).strip("_")
