import logging
import pandas as pd
from utils.ai.xai_util import enrich_reason as xai_enrich_reason
from utils.db.news_db_util import get_news_df, update_records, get_news_by_id
from utils.logging.log_util import get_logger

logger = get_logger(__name__)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def enrich_reason(df):
    logging.info("Starting summary enrichment process")
    def apply_summary(row):
        try:
            if pd.isna(row['predicted_move']):
                logging.info(f"Skipping record for {row.get('link', 'unknown link')}: No predicted move")
                return None

            text = row.get('content') or row.get('title')
            if not text:
                logging.warning(f"Skipping record for {row.get('link', 'unknown link')}: No content or title found")
                return None

            # Pass both predicted_move and predicted_side to include ML context
            predicted_side = row.get('predicted_side', None)
            reason = xai_enrich_reason(text, row['predicted_move'], predicted_side)
            logging.info(f"Generated AI summary for {row['link']} (first 50 chars): {reason[:50]}...")
            return reason
        except Exception as e:
            logging.error(f"Error summarizing news for {row['link']}: {e}")
            return None

    df['reason'] = df.apply(apply_summary, axis=1)
    logging.info(f"Summary enrichment completed for {len(df)} items")
    return df

def main():
    logging.info("Starting the enrichment process")

    try:
        df = get_news_df()

        logging.info(f"Successfully fetched news items. Proceeding with enrichment.")
        df_to_enrich = df[df['predicted_move'].notna()]

        logging.info(f"Total news items: {len(df)}")
        logging.info(f"News items with predicted move: {len(df_to_enrich)}")

        if df_to_enrich.empty:
            logging.info("No news items with predicted move found. Exiting.")
            return

        enriched_df = enrich_reason(df_to_enrich)

        # Print statistics
        enriched_rows = len(enriched_df)
        successful_enrichments = enriched_df['reason'].notna().sum()

        logging.info(f"Processed news items: {enriched_rows}")
        logging.info(f"Successfully enriched items: {successful_enrichments}")
        logging.info(f"Percentage successfully enriched: {(successful_enrichments / enriched_rows) * 100:.2f}%")

        logging.info("Updating records in the database")
        update_records(enriched_df)
        logging.info("Database update completed")

        if not enriched_df.empty:
            logging.info(f"Sample enriched reason:")
            logging.info(enriched_df['reason'].iloc[0])

    except Exception as e:
        logging.exception(f"An error occurred during the enrichment process: {e}")

if __name__ == "__main__":
    main()
