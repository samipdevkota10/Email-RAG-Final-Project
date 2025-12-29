"""
Optimized Batch Processor for Email Offer Extraction.
Uses 'Ghost Records' to track processed emails without changing DB schema.
Features: Single DB connection, Bulk Inserts, and Infinite Loop Prevention.
"""

import sys
import os
import logging
from typing import List, Tuple, Optional, Dict
from datetime import datetime
from decimal import Decimal

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Database.dbconnection import DBConnection
from src.extraction.html_cleaner import extract_candidate_blocks
from src.extraction.offer_extractor import OfferExtractor, Offer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fetch_email_batch(
    cursor,
    limit: int = 50,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> List[Tuple[int, Optional[str], Optional[str]]]:
    """
    Fetch a batch of unprocessed emails using an existing cursor.
    Logic: Fetches emails that do NOT exist in email_offers table (including NO_OFFER records).
    """
    where_clauses = [
        """
        NOT EXISTS (
            SELECT 1 FROM email_offers eo WHERE eo.email_id = e.email_id
        )
        """
    ]
    params = []
    
    if start_date:
        where_clauses.append("e.received_datetime >= %s")
        params.append(start_date)
    
    if end_date:
        where_clauses.append("e.received_datetime < %s")
        params.append(end_date)
    
    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT e.email_id, e.header_text, e.body_html
        FROM emails e
        WHERE {where_sql}
        ORDER BY e.received_datetime DESC NULLS LAST, e.email_id DESC
        LIMIT %s
    """
    params.append(limit)
    
    cursor.execute(sql, params)
    return cursor.fetchall()


def save_offers_bulk(cursor, email_id: int, offers: List[Offer], is_ghost: bool = False) -> int:
    """
    Save offers using bulk insertion for performance.
    """
    if not offers:
        return 0
    
    offer_values = []
    for offer in offers:
        # Determine confidence: 0.0 for Ghost Records, 1.0 for Regex Matches
        confidence = Decimal("0.0") if is_ghost else Decimal("1.0")

        # Handle nullable decimals
        percent_off = Decimal(str(offer.value)) if (offer.value and offer.discount_type == "PERCENT") else None
        amount_off = Decimal(str(offer.value)) if (offer.value and offer.discount_type == "AMOUNT") else None
        min_spend = Decimal(str(offer.min_spend)) if offer.min_spend else None

        offer_values.append((
            email_id,
            offer.discount_type,
            percent_off,
            amount_off,
            offer.currency or "USD",
            offer.is_up_to,
            min_spend,
            offer.promo_code,
            offer.offer_text[:500], # Truncate text just in case
            confidence
        ))

    sql = """
        INSERT INTO email_offers (
            email_id, discount_type, percent_off, amount_off, currency,
            is_up_to, min_spend, promo_code, offer_text, confidence
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    try:
        cursor.executemany(sql, offer_values)
        return len(offer_values)
    except Exception as e:
        logger.error(f"Failed to save offers for Email {email_id}: {e}")
        raise e


def update_etl_run(cursor, pipeline_name: str, last_email_id: int):
    """Update ETL run tracking."""
    sql = """
        INSERT INTO etl_runs (pipeline, last_email_id, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (pipeline)
        DO UPDATE SET
            last_email_id = EXCLUDED.last_email_id,
            updated_at = NOW()
    """
    cursor.execute(sql, (pipeline_name, last_email_id))


def process_batch(
    limit: int = 50,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    pipeline_name: str = "poc_extraction",
    use_db_prefix: bool = False
) -> Dict:
    """
    Process emails in batches for offer extraction.
    
    Args:
        limit: Maximum emails to process in this run (None = process all)
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
        pipeline_name: Name for ETL tracking
        use_db_prefix: If True, use DB_* environment variables
    """
    logger.info(f"🚀 Starting batch processing (limit={limit}, use_db_prefix={use_db_prefix})...")
    
    db = DBConnection(use_db_prefix=use_db_prefix)
    conn, cursor = None, None
    stats = {
        "emails_processed": 0,
        "offers_extracted": 0,
        "emails_with_offers": 0,
        "empty_emails": 0,
        "errors": 0
    }

    try:
        # 1. Open ONE connection for the whole batch
        conn, cursor = db.connect()
        
        # 2. Fetch Data
        emails = fetch_email_batch(cursor, limit, start_date, end_date)
        
        if not emails:
            logger.info("ℹ️  No pending emails found.")
            return stats

        logger.info(f"📧 Processing {len(emails)} emails...")
        extractor = OfferExtractor()
        last_email_id = None

        # 3. Process Loop
        for email_id, header, body in emails:
            try:
                candidate_text = extract_candidate_blocks(header, body)
                offers = extractor.extract(candidate_text) 
                
                if offers:
                    # Case A: Real offers found
                    count = save_offers_bulk(cursor, email_id, offers, is_ghost=False)
                    stats["offers_extracted"] += count
                    stats["emails_with_offers"] += 1
                else:
                    # Case B: No offers found ("Ghost Record")
                    # We create a dummy offer to satisfy NOT EXISTS check
                    ghost_offer = Offer(
                        discount_type="NO_OFFER",
                        offer_text="Scan complete: No offers detected",
                        value=None,
                        currency="USD"
                    )
                    # Insert the ghost record
                    save_offers_bulk(cursor, email_id, [ghost_offer], is_ghost=True)
                    stats["empty_emails"] += 1
                
                stats["emails_processed"] += 1
                last_email_id = email_id

            except Exception as e:
                # If a specific email crashes, log it and move to the next
                # We do NOT rollback here, or we lose progress on previous emails
                logger.error(f"❌ Error processing Email {email_id}: {e}")
                stats["errors"] += 1
                continue
        
        # 4. Update State & Commit
        if last_email_id:
            update_etl_run(cursor, pipeline_name, last_email_id)
        
        conn.commit()
        logger.info("✅ Batch transaction committed successfully.")

    except Exception as e:
        logger.critical(f"🔥 Critical Batch Failure: {e}")
        if conn:
            conn.rollback()
    finally:
        if db:
            db.close()

    logger.info(f"📊 Summary: {stats}")
    return stats


def process_all_2025(use_db_prefix: bool = False, batch_size: int = 1000):
    """
    Process all emails from 2025 in batches.
    This function will loop until all 2025 emails are processed.
    """
    logger.info("🚀 Starting full 2025 extraction...")
    
    total_stats = {
        "emails_processed": 0,
        "offers_extracted": 0,
        "emails_with_offers": 0,
        "empty_emails": 0,
        "errors": 0,
        "batches_run": 0
    }
    
    start_date = "2025-01-01"
    end_date = "2026-01-01"
    
    while True:
        logger.info(f"📦 Processing batch {total_stats['batches_run'] + 1}...")
        
        batch_stats = process_batch(
            limit=batch_size,
            start_date=start_date,
            end_date=end_date,
            pipeline_name="2025_full_extraction",
            use_db_prefix=use_db_prefix
        )
        
        # Accumulate stats
        for key in total_stats:
            if key in batch_stats:
                total_stats[key] += batch_stats[key]
        total_stats["batches_run"] += 1
        
        # If no emails were processed, we're done
        if batch_stats["emails_processed"] == 0:
            logger.info("✅ All 2025 emails have been processed!")
            break
        
        logger.info(f"📊 Batch {total_stats['batches_run']} complete. Total so far: {total_stats['emails_processed']} emails")
    
    logger.info(f"🎉 Full 2025 extraction complete!")
    logger.info(f"   Total batches: {total_stats['batches_run']}")
    logger.info(f"   Total emails: {total_stats['emails_processed']}")
    logger.info(f"   Emails with offers: {total_stats['emails_with_offers']}")
    logger.info(f"   Total offers: {total_stats['offers_extracted']}")
    logger.info(f"   Empty emails: {total_stats['empty_emails']}")
    logger.info(f"   Errors: {total_stats['errors']}")
    
    return total_stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch process emails for offer extraction")
    parser.add_argument("--limit", type=int, default=50, help="Max emails to process")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--use-db-prefix", action="store_true", help="Use DB_* environment variables")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for processing")
    parser.add_argument("--all-2025", action="store_true", help="Process all 2025 emails (loops until done)")
    args = parser.parse_args()
    
    if args.all_2025:
        process_all_2025(use_db_prefix=args.use_db_prefix, batch_size=args.batch_size)
    else:
        process_batch(
            limit=args.limit,
            start_date=args.start_date,
            end_date=args.end_date,
            use_db_prefix=args.use_db_prefix
        )