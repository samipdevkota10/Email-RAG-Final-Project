"""
Test script for offer extraction POC.
Runs extraction on a small batch and prints results for manual review.
"""

import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Database.dbconnection import DBConnection
from src.extraction.batch_processor import process_batch, fetch_email_batch
from src.extraction.html_cleaner import extract_candidate_blocks
from src.extraction.offer_extractor import OfferExtractor


def print_extraction_details(email_id: int, header_text: str, body_html: str):
    """Print detailed extraction information for an email."""
    from src.extraction.html_cleaner import extract_candidate_blocks
    from src.extraction.offer_extractor import OfferExtractor
    
    print(f"\n{'='*60}")
    print(f"Email ID: {email_id}")
    print(f"{'='*60}")
    
    # Extract candidate text
    candidate_text = extract_candidate_blocks(header_text, body_html)
    print(f"\n📝 Candidate Text (first 500 chars):")
    print(candidate_text[:500] + ("..." if len(candidate_text) > 500 else ""))
    
    # Extract offers
    extractor = OfferExtractor()
    offers = extractor.extract(candidate_text)
    
    print(f"\n🎯 Extracted Offers: {len(offers)}")
    for i, offer in enumerate(offers, 1):
        print(f"\n  Offer {i}:")
        print(f"    Type: {offer.discount_type}")
        if offer.value:
            if offer.discount_type == "PERCENT":
                print(f"    Percent Off: {offer.value}%")
            elif offer.discount_type == "AMOUNT":
                currency_symbol = offer.currency or "USD"
                print(f"    Amount Off: {currency_symbol} {offer.value}")
        if offer.is_up_to:
            print(f"    Is 'Up To': Yes")
        if offer.min_spend:
            print(f"    Min Spend: ${offer.min_spend}")
        if offer.promo_code:
            print(f"    Promo Code: {offer.promo_code}")
        print(f"    Confidence: 1.0 (regex match)")
        print(f"    Text: {offer.offer_text[:100]}...")


def test_single_email(email_id: int):
    """Test extraction on a single email."""
    db = DBConnection()
    try:
        conn, cursor = db.connect()
        
        cursor.execute("""
            SELECT email_id, header_text, body_html
            FROM emails
            WHERE email_id = %s
        """, (email_id,))
        
        row = cursor.fetchone()
        if not row:
            print(f"❌ Email {email_id} not found")
            return
        
        email_id, header_text, body_html = row
        print_extraction_details(email_id, header_text, body_html)
    finally:
        db.close()


def test_batch_sample(limit: int = 5):
    """Test extraction on a small sample batch."""
    print(f"🧪 Testing extraction on {limit} email sample...\n")
    
    # Fetch sample emails
    emails = fetch_email_batch(limit=limit, exclude_processed=False)
    
    if not emails:
        print("❌ No emails found")
        return
    
    for email_id, header_text, body_html in emails:
        print_extraction_details(email_id, header_text, body_html)
    
    print(f"\n{'='*60}")
    print("✅ Sample test complete")


def show_statistics():
    """Show extraction statistics from database."""
    db = DBConnection()
    try:
        conn, cursor = db.connect()
        
        # Total offers
        cursor.execute("SELECT COUNT(*) FROM email_offers")
        total_offers = cursor.fetchone()[0]
        
        # Offers by type
        cursor.execute("""
            SELECT discount_type, COUNT(*) as count
            FROM email_offers
            GROUP BY discount_type
            ORDER BY count DESC
        """)
        by_type = cursor.fetchall()
        
        # Emails with offers
        cursor.execute("SELECT COUNT(DISTINCT email_id) FROM email_offers")
        emails_with_offers = cursor.fetchone()[0]
        
        # Average confidence
        cursor.execute("SELECT AVG(confidence) FROM email_offers")
        avg_confidence = cursor.fetchone()[0]
        
        print("\n📊 Extraction Statistics:")
        print(f"   Total offers extracted: {total_offers}")
        print(f"   Emails with offers: {emails_with_offers}")
        if avg_confidence:
            print(f"   Average confidence: {avg_confidence:.3f}")
        print(f"\n   Offers by type:")
        for discount_type, count in by_type:
            print(f"     {discount_type}: {count}")
        
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test offer extraction")
    parser.add_argument("--email-id", type=int, help="Test on specific email ID")
    parser.add_argument("--sample", type=int, default=5, help="Test on sample of N emails")
    parser.add_argument("--stats", action="store_true", help="Show extraction statistics")
    parser.add_argument("--run-batch", action="store_true", help="Run actual batch processing")
    parser.add_argument("--limit", type=int, default=20, help="Batch processing limit")
    
    args = parser.parse_args()
    
    if args.stats:
        show_statistics()
    elif args.email_id:
        test_single_email(args.email_id)
    elif args.run_batch:
        process_batch(limit=args.limit)
    else:
        test_batch_sample(limit=args.sample)

