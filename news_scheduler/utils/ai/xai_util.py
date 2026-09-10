"""
LLM utility functions using LangChain
Uses XAI (Grok) as primary provider with Groq (Llama) fallback for all LLM operations
Uses LLMFactory for unified provider management
"""
import os
from dotenv import load_dotenv
from gptcache import cache
import logging
from utils.ai.language_util import normalize_language_code
from utils.static.tag_util import tag_list
import json
from typing import Optional, Literal

# LangChain imports
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

# Load environment variables
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class LLMFactory:
    """Factory to create LangChain LLM instances for different providers."""

    # Default models per provider (will be overridden by env vars)
    DEFAULT_MODELS = {
        'groq': 'llama-3.1-70b-versatile',
        'xai': 'grok-4.3',
    }

    @classmethod
    def create(
        cls,
        provider: Literal['groq', 'xai'] = 'xai',  # Default to XAI
        model: Optional[str] = None,
        temperature: float = 0.1,
        **kwargs
    ):
        """
        Create an LLM instance for the specified provider.

        Args:
            provider: 'groq' or 'xai'
            model: Model name (defaults to env var or provider default)
            temperature: Temperature for generation
            **kwargs: Additional arguments passed to the LLM constructor

        Returns:
            LangChain LLM instance
        """
        if provider == 'groq':
            return cls._create_groq(model, temperature, **kwargs)
        elif provider == 'xai':
            return cls._create_xai(model, temperature, **kwargs)
        else:
            raise ValueError(f"Unsupported provider: {provider}. Use 'groq' or 'xai'")

    @classmethod
    def _create_groq(cls, model: Optional[str], temperature: float, **kwargs):
        """Create a Groq LLM instance."""
        try:
            from langchain_groq import ChatGroq
        except ImportError:
            raise ImportError("langchain-groq not installed. Run: pip install langchain-groq")

        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")

        # Model priority: argument > env var > default
        model_name = model or os.getenv('GROQ_MODEL') or cls.DEFAULT_MODELS['groq']

        logger.info(f"Creating Groq LLM: model={model_name}")

        return ChatGroq(
            model=model_name,
            api_key=api_key,
            temperature=temperature,
            **kwargs
        )

    @classmethod
    def _create_xai(cls, model: Optional[str], temperature: float, **kwargs):
        """
        Create an XAI/Grok LLM instance.

        XAI uses OpenAI-compatible API, so we use ChatOpenAI with custom base_url.
        """
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("langchain-openai not installed. Run: pip install langchain-openai")

        api_key = os.getenv('XAI_API_KEY')
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable not set")

        # Model priority: argument > env var > default
        model_name = model or os.getenv('XAI_MODEL') or os.getenv('GROK_MODEL') or cls.DEFAULT_MODELS['xai']

        logger.info(f"Creating XAI/Grok LLM: model={model_name}")

        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            temperature=temperature,
            **kwargs
        )

    @classmethod
    def list_providers(cls):
        """List available providers and their status."""
        providers = {}

        # Check Groq
        groq_key = os.getenv('GROQ_API_KEY')
        providers['groq'] = {
            'available': bool(groq_key),
            'api_key_set': bool(groq_key),
            'model': os.getenv('GROQ_MODEL') or cls.DEFAULT_MODELS['groq'],
        }

        # Check XAI
        xai_key = os.getenv('XAI_API_KEY')
        providers['xai'] = {
            'available': bool(xai_key),
            'api_key_set': bool(xai_key),
            'model': os.getenv('XAI_MODEL') or os.getenv('GROK_MODEL') or cls.DEFAULT_MODELS['xai'],
        }

        return providers


# Initialize XAI LLM via factory (default provider with Groq fallback)
# Note: Model names are read from environment variables:
# - GROQ_MODEL for Groq provider
# - XAI_MODEL (or legacy GROK_MODEL) for XAI provider
llm = LLMFactory.create('xai')

# Initialize output parser
output_parser = StrOutputParser()

# Initialize cache
cache.init()
# Note: gptcache may need XAI-specific configuration

def _invoke_llm(system_prompt: str, user_prompt: str, max_tokens: int = None, provider: str = 'xai') -> str:
    """
    Helper function to invoke LLM via LangChain using factory with fallback

    Tries XAI first, falls back to Groq if XAI fails (especially 429 errors)

    Args:
        system_prompt: System message/prompt
        user_prompt: User message/prompt
        max_tokens: Maximum tokens to generate (optional)
        provider: LLM provider ('xai' or 'groq') - defaults to 'xai' with Groq fallback

    Returns:
        Response text from LLM
    """
    # Try XAI first (primary provider)
    if provider == 'xai':
        try:
            # Get XAI LLM instance from factory
            llm_instance = LLMFactory.create('xai')

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]

            # Configure invocation kwargs
            invoke_kwargs = {}
            if max_tokens:
                invoke_kwargs['max_tokens'] = max_tokens

            # Invoke XAI LLM
            response = llm_instance.invoke(messages, **invoke_kwargs)

            # Parse output
            if hasattr(response, 'content'):
                return response.content
            else:
                # Fallback: try to get text directly
                return str(response)

        except Exception as xai_error:
            logger.warning(f"XAI LLM failed: {xai_error}")
            logger.info(f"XAI error type: {type(xai_error)}")
            error_str = str(xai_error).lower()
            logger.info(f"Error string: '{error_str}'")

            # ALWAYS fall back to Groq when XAI fails (any error)
            logger.warning("=" * 80)
            logger.warning("XAI FAILED - FALLING BACK TO GROQ")
            logger.warning(f"XAI Error: {xai_error}")
            logger.warning("=" * 80)

            # Fall back to Groq
            try:
                llm_instance = LLMFactory.create('groq')
                logger.warning("âœ… Created Groq LLM instance for fallback")

                # Invoke Groq LLM
                response = llm_instance.invoke(messages, **invoke_kwargs)
                logger.warning("âœ… Successfully invoked Groq LLM - Using Groq response")

                # Parse output
                if hasattr(response, 'content'):
                    logger.warning("âœ… Returning Groq response content")
                    return response.content
                else:
                    logger.warning("âœ… Returning Groq response as string")
                    return str(response)

            except Exception as groq_error:
                logger.error("=" * 80)
                logger.error("âŒ BOTH XAI AND GROQ FAILED")
                logger.error(f"XAI Error: {xai_error}")
                logger.error(f"Groq Error: {groq_error}")
                logger.error("=" * 80)
                raise groq_error

    # Direct provider request (not xai)
    try:
        # Get LLM instance from factory
        llm_instance = LLMFactory.create(provider)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        # Configure invocation kwargs
        invoke_kwargs = {}
        if max_tokens:
            invoke_kwargs['max_tokens'] = max_tokens

        # Invoke LLM
        response = llm_instance.invoke(messages, **invoke_kwargs)

        # Parse output
        if hasattr(response, 'content'):
            return response.content
        else:
            # Fallback: try to get text directly
            return str(response)

    except Exception as e:
        logger.error(f"Error invoking {provider} LLM: {e}")
        raise

def tag_news(news, tags):
    """
    Classify news articles into event categories using LLM

    Args:
        news: News article text (title + content)
        tags: Comma-separated list of available tags

    Returns:
        Tag name string
    """
    system_prompt = """You are a financial news classifier. Classify news articles into the most appropriate category from the provided list.

CRITICAL CLASSIFICATION RULES - READ CAREFULLY:

âš ï¸ ESG MISCLASSIFICATION PREVENTION:
- "environmental_social_governance" (ESG) should ONLY be used for:
  * Explicit ESG reports, sustainability reports, CSR reports
  * Climate change initiatives, carbon reduction goals
  * Social responsibility programs, community initiatives
  * Governance structure changes (board diversity, ethics policies)
  * Environmental impact assessments
- DO NOT classify as ESG:
  * Share buybacks, repurchases, treasury shares â†’ use "changes_in_companys_own_shares"
  * Voting rights, shareholder rights â†’ use "voting_rights" or "changes_in_share_capital_and_votes"
  * Financial results, earnings â†’ use "earnings_releases_and_operating_results" or "financial_results"
  * Regulatory filings, compliance â†’ use "regulatory_filings" or "company_regulatory_filings"
  * Management changes â†’ use "management_changes"
  * Corporate actions â†’ use "corporate_action"
  * General company announcements â†’ use "press_releases" or more specific category

SHARE CAPITAL & VOTING RIGHTS (NOT ESG):
- "changes_in_share_capital_and_votes": Number of shares, voting rights updates, share capital changes, monthly share declarations
- "changes_in_companys_own_shares": Share buybacks, repurchases, treasury shares, share cancellations
- "voting_rights": Voting rights announcements, shareholder voting information, voting rights notifications
- "share_capital_increase": Capital increases, new share issuances, capital raises
- "shares_issue": New share issues, share offerings, stock issuances
âš ï¸ NEVER classify these as "environmental_social_governance" - they are financial/regulatory, not ESG

ESG (ENVIRONMENTAL, SOCIAL, GOVERNANCE) - USE SPARINGLY:
- "environmental_social_governance": ONLY for actual ESG reports, sustainability initiatives, CSR programs, climate goals, social responsibility, governance practices
âš ï¸ NOT for: share buybacks, voting rights, financial results, regulatory filings, management changes, corporate actions

FINANCIAL RESULTS:
- "earnings_releases_and_operating_results": Quarterly/annual earnings, profit/loss, revenue
- "financial_results": Financial performance, balance sheets, income statements
- "interim_information": Interim financial reports, quarterly updates
- "annual_report": Annual financial reports and statements

DIVIDENDS:
- "dividend_reports_and_estimates": Dividend announcements, dividend payments, dividend estimates
- "ex_dividend_date": Ex-dividend date announcements

CORPORATE ACTIONS:
- "corporate_action": General corporate actions (stock splits, spin-offs, etc.)
- "mergers_acquisitions": M&A deals, acquisitions, mergers
- "joint_venture": Joint venture announcements
- "partnerships": Strategic partnerships, business partnerships

MANAGEMENT & GOVERNANCE:
- "management_changes": CEO appointments, executive changes, board changes
- "management_statements": CEO/management comments, forward-looking statements
- "major_shareholder_announcements": Major shareholder changes, ownership disclosures

PRODUCTS & SERVICES:
- "product_services_announcement": New products, service launches, product updates
- "patents": Patent filings, patent grants, intellectual property

REGULATORY & FILINGS:
- "regulatory_filings": SEC filings, regulatory submissions, compliance filings
- "company_regulatory_filings": Company-specific regulatory filings
- "exchange_announcement": Stock exchange announcements, listing changes

RESEARCH & ANALYSIS:
- "market_research_reports": Market research, industry analysis reports
- "research_analysis_and_reports": Research reports, analyst reports
- "analyst_coverage": Analyst coverage, analyst ratings

MEETINGS & EVENTS:
- "annual_general_meeting": AGM announcements, annual meetings
- "annual_meetings_shareholder_rights": AGM with shareholder rights focus
- "conference_call_webinar": Earnings calls, investor calls, webinars
- "trade_show": Trade show participation, exhibitions

FINANCING:
- "financing_agreements": Loan agreements, credit facilities, financing deals
- "capital_investment": Capital expenditure, investment announcements
- "initial_public_offerings": IPO announcements, going public

OTHER CATEGORIES:
- "advisory": Advisory notices, warnings
- "bankruptcy": Bankruptcy filings, insolvency
- "bond_fixing": Bond pricing, bond fixing
- "business_contracts": Business contract announcements
- "clinical_study": Clinical trials, medical studies (healthcare/biotech)
- "contests_awards": Awards, competitions, recognition
- "feature_article": Feature articles, editorial content
- "financial_calendar": Financial calendar, earnings calendar
- "fund_data_announcement": Fund data, NAV announcements
- "geographic_expansion": Market expansion, new markets
- "government_news": Government-related news, policy impacts
- "law_legal_issues": Legal issues, lawsuits, legal proceedings
- "licensing_agreements": Licensing deals, technology licenses
- "observation_status": Exchange observation status, listing status
- "pre-release_comments": Pre-earnings comments, guidance
- "press_releases": General press releases (use if no better fit)
- "prospectus_announcement": Prospectus filings, offering documents
- "trading_information": Trading halts, trading updates
- "warrants_and_certificates": Warrants, certificates, derivatives

CLASSIFICATION PROCESS:
1. Read the news article carefully - identify the PRIMARY topic/subject
2. Check if it mentions ESG, sustainability, CSR, climate, or social responsibility explicitly
   - If YES and it's an ESG report/initiative â†’ use "environmental_social_governance"
   - If NO â†’ DO NOT use ESG, find a more specific category
3. For Euronext and European exchanges: Many announcements are regulatory/financial, NOT ESG
   - Share transactions, voting rights, capital changes â†’ NOT ESG
   - Financial results, earnings â†’ NOT ESG
   - Regulatory compliance â†’ NOT ESG
4. Match to the MOST SPECIFIC category available
5. If unsure between two categories, choose the more specific one
6. Avoid generic categories like "press_releases" if a more specific category fits
7. When in doubt between ESG and another category, choose the other category (ESG is overused)

EXAMPLES:
- "Company announces share buyback program" â†’ "changes_in_companys_own_shares" (NOT ESG)
- "Company publishes ESG sustainability report" â†’ "environmental_social_governance" (YES ESG)
- "Company reports Q3 earnings" â†’ "earnings_releases_and_operating_results" (NOT ESG)
- "Company announces voting rights change" â†’ "voting_rights" (NOT ESG)
- "Company commits to carbon neutrality by 2030" â†’ "environmental_social_governance" (YES ESG)

Respond with ONLY the tag name, nothing else."""

    user_prompt = f'Classify this news article into the most appropriate category from this list: {tags}\n\nNews article:\n"{news}"'

    try:
        tag = _invoke_llm(system_prompt, user_prompt)
        tag = tag.strip()

        # Clean up the response: remove quotes, extra text, and extract just the tag
        tag = tag.strip('"\'`').strip()
        # If response contains the tag in a sentence, try to extract it
        if tag not in tag_list:
            # Try to find a matching tag in the response
            for possible_tag in tag_list:
                if possible_tag.lower() in tag.lower() or tag.lower() in possible_tag.lower():
                    tag = possible_tag
                    break

        return tag
    except Exception as e:
        # Check if it's a rate limit error that should trigger fallback
        error_str = str(e).lower()
        if '429' in error_str or 'exhausted' in error_str or 'limit' in error_str or 'credit' in error_str or 'spending limit' in error_str:
            logger.warning(f"Rate limit error in tag_news, re-raising for fallback: {e}")
            raise e  # Re-raise so fallback can happen
        logger.error(f"Error in tag_news: {e}")
        return "press_releases"  # Fallback to generic category

def enrich_reason(content, predicted_move, predicted_side=None):
    """
    Generate market analysis reason using LLM with ML prediction context

    Args:
        content: News content
        predicted_move: Predicted price move percentage (from ML model)
        predicted_side: Predicted side from ML model (UP/DOWN/NEUTRAL)

    Returns:
        Reason text string
    """
    system_prompt = """You are a financial analyst providing concise market insights. Your responses should be clear and readable without using any special characters or explicit formatting such as new lines. Use standard punctuation and avoid line breaks within sentences. Separate ideas with periods and commas as needed."""

    if predicted_move is not None:
        # Determine direction based on predicted_move and predicted_side
        if predicted_side and predicted_side.upper() == 'NEUTRAL':
            direction = "neutral"
            move_desc = f"minimal movement ({predicted_move:+.2f}%)"
        elif abs(predicted_move) < 0.5:  # Very small move, treat as neutral
            direction = "neutral"
            move_desc = f"minimal movement ({predicted_move:+.2f}%)"
        else:
            direction = "up" if predicted_move > 0 else "down"
            move_desc = f"{direction}ward by {predicted_move:+.2f}%"

        # Include ML prediction context in the prompt
        ml_context = f"ML model predicts {predicted_side or direction.upper()}" if predicted_side else f"ML model predicts {direction.upper()}"

        user_prompt = f"""Analyze: "{content}" {ml_context} with {move_desc}. In less than 40 words: 1. Explain why the ML model predicts this {direction} movement based on the news content. 2. Briefly discuss potential market implications. 3. Naturally include "ML model predicts {move_desc}". Be concise yet comprehensive. Ensure a complete response with no cut-off sentences."""
    else:
        user_prompt = f'In less than 40 words, summarize the potential market impact of this news. Ensure a complete response with no cut-off sentences: "{content}"'

    try:
        reason = _invoke_llm(system_prompt, user_prompt, max_tokens=80)
        return reason.strip()
    except Exception as e:
        # Check if it's a rate limit error that should trigger fallback
        error_str = str(e).lower()
        if '429' in error_str or 'exhausted' in error_str or 'limit' in error_str or 'credit' in error_str or 'spending limit' in error_str:
            logger.warning(f"Rate limit error in enrich_reason, re-raising for fallback: {e}")
            raise e  # Re-raise so fallback can happen
        logger.error(f"Error in enrich_reason: {e}")
        return "Market impact analysis unavailable."

def extract_ticker(company):
    """
    Extract ticker symbol from company name using XAI

    Args:
        company: Company name

    Returns:
        Ticker symbol string or None
    """
    prompt = f'Extract the company or issuer ticker symbol corresponding to the company name provided. Return only the ticker symbol in uppercase, without any additional text. If you cannot assign a ticker symbol, return "N/A". Company name: "{company}"'

    try:
        ticker = _invoke_llm("", prompt)
        ticker = ticker.strip().upper()
        return ticker if ticker != "N/A" else None
    except Exception as e:
        # Check if it's a rate limit error that should trigger fallback
        error_str = str(e).lower()
        if '429' in error_str or 'exhausted' in error_str or 'limit' in error_str or 'credit' in error_str or 'spending limit' in error_str:
            logger.warning(f"Rate limit error in extract_ticker, re-raising for fallback: {e}")
            raise e  # Re-raise so fallback can happen
        logger.error(f"Error in extract_ticker: {e}")
        return None

def extract_issuer(news):
    """
    Extract company/issuer name from news text using XAI

    Args:
        news: News text

    Returns:
        Company name string or None
    """
    prompt = f'Extract the company or issuer name corresponding to the text provided. Return concise entity name only. If you cannot assign a ticker symbol, return "N/A". News: "{news}"'

    try:
        issuer = _invoke_llm("", prompt)
        issuer = issuer.strip().upper()
        return issuer if issuer != "N/A" else None
    except Exception as e:
        # Check if it's a rate limit error that should trigger fallback
        error_str = str(e).lower()
        if '429' in error_str or 'exhausted' in error_str or 'limit' in error_str or 'credit' in error_str or 'spending limit' in error_str:
            logger.warning(f"Rate limit error in extract_issuer, re-raising for fallback: {e}")
            raise e  # Re-raise so fallback can happen
        logger.error(f"Error in extract_issuer: {e}")
        return None

def detect_language(title):
    """
    Detect language of text using XAI

    Args:
        title: Text to detect language for

    Returns:
        Language code string
    """
    prompt = f'Detect the language of this text and return only the 2-letter ISO language code (e.g. "en" for English, "sv" for Swedish). If you cannot determine the exact ISO code, return the full language name: "{title}"'

    try:
        language = _invoke_llm("", prompt)
        language = language.strip().lower()

        # Use the normalized language code function
        return normalize_language_code(language)
    except Exception as e:
        # Check if it's a rate limit error that should trigger fallback
        error_str = str(e).lower()
        if '429' in error_str or 'exhausted' in error_str or 'limit' in error_str or 'credit' in error_str or 'spending limit' in error_str:
            logger.warning(f"Rate limit error in detect_language, re-raising for fallback: {e}")
            raise e  # Re-raise so fallback can happen
        logger.error(f"Error in detect_language: {e}")
        return "en"  # Fallback to English

def translate_to_english(text, source_language):
    """
    Translate text to English using XAI

    Args:
        text: Text to translate
        source_language: Source language code

    Returns:
        Translated text string
    """
    prompt = f'Translate the following text from {source_language} to English. Return only the translation without any additional text or formatting: "{text}"'

    try:
        translation = _invoke_llm("", prompt)
        return translation.strip()
    except Exception as e:
        # Check if it's a rate limit error that should trigger fallback
        error_str = str(e).lower()
        if '429' in error_str or 'exhausted' in error_str or 'limit' in error_str or 'credit' in error_str or 'spending limit' in error_str:
            logger.warning(f"Rate limit error in translate_to_english, re-raising for fallback: {e}")
            raise e  # Re-raise so fallback can happen
        logger.error(f"Error in translate_to_english: {e}")
        return text  # Fallback to original text

def get_prediction_from_xai(content):
    """
    Get price movement prediction from XAI

    Args:
        content: News content

    Returns:
        Dictionary with 'move' (float) and 'side' (str) predictions, or None
    """
    system_prompt = """You are a financial market analyst. Analyze news content and predict potential price movements.
    Return only a JSON object with two fields:
    - 'move': predicted percentage move (float between 0.1 and 10.0)
    - 'side': direction ('up' or 'down')
    For neutral or unclear news, return null for both fields."""

    user_prompt = f'Predict the likely price movement based on this news: "{content}"'

    try:
        response = _invoke_llm(system_prompt, user_prompt)

        # Try to parse JSON from response
        # Remove markdown code blocks if present
        response = response.strip()
        if response.startswith('```json'):
            response = response[7:]
        if response.startswith('```'):
            response = response[3:]
        if response.endswith('```'):
            response = response[:-3]
        response = response.strip()

        result = json.loads(response)

        # Validate the prediction
        if result.get('move') is not None and result.get('side') is not None:
            move = float(result['move'])
            side = result['side'].lower()

            # Ensure move is positive and side is valid
            if move > 0 and side in ['up', 'down']:
                # Make move negative if side is down
                if side == 'down':
                    move = -move
                return {'move': move, 'side': side}

        return None

    except Exception as e:
        # Check if it's a rate limit error that should trigger fallback
        error_str = str(e).lower()
        if '429' in error_str or 'exhausted' in error_str or 'limit' in error_str or 'credit' in error_str or 'spending limit' in error_str:
            logger.warning(f"Rate limit error in get_prediction_from_xai, re-raising for fallback: {e}")
            raise e  # Re-raise so fallback can happen
        logger.error(f"Error getting prediction from XAI: {str(e)}")
        return None

# Alias for backward compatibility
get_prediction_from_openai = get_prediction_from_xai
