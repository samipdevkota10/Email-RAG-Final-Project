import unittest
import sys
import os
import logging
import json
from decimal import Decimal

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from src.extraction.offer_extractor import OfferExtractor, Offer

# Configure logging to show up in the console
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

class RichLoggingMixin:
    """Helper class to pretty-print extraction results during tests."""
    
    def extract_and_log(self, text: str):
        """
        Runs extraction and logs the input/output in a readable JSON format.
        Returns the offers list for assertions.
        """
        print(f"\n{'='*60}")
        print(f"🧪 TEST: {self._testMethodName}")
        print(f"{'-'*60}")
        print(f"📄 INPUT TEXT:\n\"{text.strip()}\"")
        print(f"{'-'*60}")
        
        offers = self.extractor.extract(text)
        
        if not offers:
            print("❌ RESULT: No offers found.")
        else:
            print(f"✅ RESULT: Found {len(offers)} offer(s):")
            for i, offer in enumerate(offers, 1):
                # Convert to dict and simplify specific fields for readable logging
                data = offer.to_dict()
                # Clean up None values for cleaner logs
                clean_data = {k: v for k, v in data.items() if v is not None}
                print(f"   {i}. {json.dumps(clean_data, default=str, indent=None)}")
        
        print(f"{'='*60}\n")
        return offers

class TestOfferExtractor(unittest.TestCase, RichLoggingMixin):

    def setUp(self):
        self.extractor = OfferExtractor()

    def test_extract_simple_percent(self):
        text = "Get 20% off your next order."
        # Use the helper method instead of self.extractor.extract
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].discount_type, "PERCENT")
        self.assertEqual(offers[0].value, Decimal("20"))
        self.assertFalse(offers[0].is_up_to)

    def test_extract_up_to_percent(self):
        text = "Sale! Up to 50% off everything."
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].discount_type, "PERCENT")
        self.assertEqual(offers[0].value, Decimal("50"))
        self.assertTrue(offers[0].is_up_to)

    def test_extract_amount_off_prefix(self):
        text = "Save $10 on orders over $50."
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].discount_type, "AMOUNT")
        self.assertEqual(offers[0].value, Decimal("10"))
        self.assertEqual(offers[0].currency, "USD")

    def test_extract_amount_off_suffix(self):
        text = "Take an extra $20 Off at checkout."
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].discount_type, "AMOUNT")
        self.assertEqual(offers[0].value, Decimal("20"))

    def test_ignore_plain_prices(self):
        text = "Your total cart value is $50.00. Thank you."
        offers = self.extract_and_log(text)
        self.assertEqual(len(offers), 0)

    def test_currency_mapping(self):
        text = "Save €15 on EU orders and £10 on UK orders."
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 2)
        offers.sort(key=lambda x: x.value)
        
        self.assertEqual(offers[0].currency, "GBP")
        self.assertEqual(offers[1].currency, "EUR")

    def test_proximity_matching_logic(self):
        text = """
        Flash Sale!
        1. Get 20% off shoes. Use code: SAVE20 at checkout.
        ...
        2. Big Spender? Save $50 on jackets with code BIG50.
        """
        offers = self.extract_and_log(text)
        self.assertEqual(len(offers), 2)
        
        percent_offer = next(o for o in offers if o.discount_type == "PERCENT")
        amount_offer = next(o for o in offers if o.discount_type == "AMOUNT")
        
        self.assertEqual(percent_offer.promo_code, "SAVE20")
        self.assertEqual(amount_offer.promo_code, "BIG50")

    def test_min_spend_extraction(self):
        text = "Take $15 off (orders over $100)."
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].min_spend, Decimal("100"))

    def test_deduplication(self):
        text = "Get 20% off. Seriously, 20% off!"
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].value, Decimal("20"))

    def test_bogo_extraction(self):
        text = "Buy one get one free on all socks."
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].discount_type, "BOGO")

    def test_free_shipping(self):
        text = "Plus enjoy Free Shipping on all orders."
        offers = self.extract_and_log(text)
        
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].discount_type, "FREE_SHIP")

if __name__ == '__main__':
    # Verbosity 2 ensures standard output is printed nicely
    unittest.main(verbosity=2)