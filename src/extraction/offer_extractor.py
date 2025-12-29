import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from decimal import Decimal, InvalidOperation

@dataclass(eq=False)  # Disable auto-generated __eq__ so we can use custom one
class Offer:
    """
    Structured representation of a marketing offer.
    Uses 'decimal' for financial precision.
    """
    discount_type: str  # PERCENT, AMOUNT, BOGO, FREE_SHIP
    value: Optional[Decimal] = None
    currency: Optional[str] = None
    min_spend: Optional[Decimal] = None
    promo_code: Optional[str] = None
    is_up_to: bool = False
    offer_text: str = ""
    span: Tuple[int, int] = field(default=(0, 0), repr=False) # Location in text

    def to_dict(self) -> Dict:
        """Export to database-friendly dictionary."""
        return {
            "type": self.discount_type,
            "value": str(self.value) if self.value else None,
            "currency": self.currency,
            "code": self.promo_code,
            "min_spend": str(self.min_spend) if self.min_spend else None,
            "condition": "UP_TO" if self.is_up_to else "FIXED",
            "text": self.offer_text
        }

    def __hash__(self):
        """Smart deduplication key - only core offer attributes, not metadata."""
        return hash((
            self.discount_type, 
            self.value, 
            self.currency,
            self.is_up_to
        ))
    
    def __eq__(self, other):
        """Equality check for deduplication - ignores promo_code, min_spend, offer_text, span."""
        if not isinstance(other, Offer):
            return False
        return (
            self.discount_type == other.discount_type and
            self.value == other.value and
            self.currency == other.currency and
            self.is_up_to == other.is_up_to
        )

class OfferExtractor:
    def __init__(self):
        # --- 1. Percentages ---
        # Matches "Up to 50%"
        self.up_to_pattern = re.compile(r'\bup\s+to\s+(\d{1,3})\s?%', re.IGNORECASE)
        # Matches "20% off", "Save 20%"
        self.percent_pattern = re.compile(r'(?:save|get|take)?\s*(\d{1,3})\s?%\s*(?:off|discount)?', re.IGNORECASE)

        # --- 2. Amounts (Safe Split Pattern) ---
        # Prevents "Total cost is $50" from being seen as an offer.
        # Requires either a Verb (Save $10) OR a Tail ($10 Off).
        self.amount_pattern = re.compile(
            r'(?:'
            # Option A: Verb + Currency + Value (e.g. "Save $10", "Save €15")
            r'(?P<verb>save|get|take)\s+(?P<cur_a>[$£€])\s*(?P<val_a>\d+(?:\.\d{1,2})?)'
            r'|'
            # Option B: Currency + Value + Tail (e.g. "$10 Off", "$20 discount")
            r'(?P<cur_b>[$£€])\s*(?P<val_b>\d+(?:\.\d{1,2})?)\s+(?P<tail>off|discount|cash\s*back)'
            r'|'
            # Option C: Currency + Value after "and" or comma (e.g. "and £10" in "Save €15 and £10")
            r'(?:and|,)\s+(?P<cur_c>[$£€])\s*(?P<val_c>\d+(?:\.\d{1,2})?)(?:\s+on|\s+for|$)'
            r')',
            re.IGNORECASE
        )

        # --- 3. Metadata Extractors ---
        self.bogo_pattern = re.compile(r'\bbuy\s+(?:\d+|one)\s+get\s+(?:\d+|one)?', re.IGNORECASE)
        self.free_ship_pattern = re.compile(r'\bfree\s+shipping\b', re.IGNORECASE)
        
        # Matches "Code: SAVE20", "Use promo HOLIDAY"
        # Captures the code AFTER the keyword, not the keyword itself
        self.code_pattern = re.compile(
            r'\b(?:code|promo|coupon|use)\s*[:\-]?\s*["\']?([A-Z0-9]{3,20})["\']?(?:\s|$|[.,!?;])', 
            re.IGNORECASE
        )
        
        # Matches "Orders over $50", "Min spend $100"
        self.min_spend_pattern = re.compile(
            r'(?:orders?|spend|purchase)\s+(?:over|above|of|\+|more than)\s*([$€£])?\s*(\d+)', 
            re.IGNORECASE
        )

    def extract(self, text: str) -> List[Offer]:
        """Main entry point for extraction."""
        if not text: return []

        offers = []
        
        # A. Extract Core Offers (The "What")
        offers.extend(self._extract_percents(text))
        offers.extend(self._extract_amounts(text))
        offers.extend(self._extract_bogo(text))
        offers.extend(self._extract_shipping(text))

        # B. Extract Conditions (The "How")
        # We find ALL codes/min_spends first, recording their locations.
        codes = []
        for m in self.code_pattern.finditer(text):
            code_val = m.group(1)
            # Skip if the captured group is just the keyword itself (like "CODE")
            if code_val and len(code_val) >= 3 and code_val.upper() not in ['CODE', 'PROMO', 'COUPON', 'USE']:
                codes.append({'val': code_val.upper(), 'span': m.span()})
        
        min_spends = [{'val': Decimal(m.group(2)), 'span': m.span()} for m in self.min_spend_pattern.finditer(text)]

        # C. Link Conditions to Offers (Proximity Logic)
        for offer in offers:
            # If no code attached yet, find the nearest one
            if not offer.promo_code:
                nearest_code = self._find_nearest(offer.span, codes)
                if nearest_code:
                    offer.promo_code = nearest_code['val']

            # Link nearest min_spend
            if not offer.min_spend:
                nearest_spend = self._find_nearest(offer.span, min_spends)
                if nearest_spend:
                    offer.min_spend = nearest_spend['val']

        # D. Deduplicate (Set conversion uses __hash__)
        return list(set(offers))

    def _extract_percents(self, text: str) -> List[Offer]:
        found = []
        up_to_spans = []
        
        # Priority: Check "Up To" first and record their spans
        for m in self.up_to_pattern.finditer(text):
            val = Decimal(m.group(1))
            if 0 < val <= 100:
                offer = self._make_offer(text, m, "PERCENT", val, is_up_to=True)
                found.append(offer)
                up_to_spans.append(m.span())

        # Standard Percentages (avoid overlaps with "Up To")
        for m in self.percent_pattern.finditer(text):
            match_start, match_end = m.span()
            # Skip if this percentage overlaps with any "Up To" span
            skip = False
            for up_start, up_end in up_to_spans:
                # Check if the percentage number itself is within the "up to" span
                # The percent pattern matches things like "50% off", so we check if
                # the start of our match (where the number begins) is within the "up to" span
                if up_start <= match_start < up_end:
                    skip = True
                    break
                # Also check if there's any overlap at all (more lenient)
                overlap_start = max(up_start, match_start)
                overlap_end = min(up_end, match_end)
                if overlap_start < overlap_end:
                    # If there's any overlap, skip it
                    skip = True
                    break
            
            if skip:
                continue
            
            val = Decimal(m.group(1))
            if 0 < val <= 100:
                found.append(self._make_offer(text, m, "PERCENT", val))
        
        return found

    def _extract_amounts(self, text: str) -> List[Offer]:
        found = []
        for m in self.amount_pattern.finditer(text):
            # Determine which regex group matched (A, B, or C)
            if m.group('val_a'):
                val = Decimal(m.group('val_a'))
                cur_sym = m.group('cur_a')
            elif m.group('val_b'):
                val = Decimal(m.group('val_b'))
                cur_sym = m.group('cur_b')
            elif m.group('val_c'):
                val = Decimal(m.group('val_c'))
                cur_sym = m.group('cur_c')
            else:
                continue  # Skip if no value matched
            
            currency = self._map_currency(cur_sym)
            found.append(self._make_offer(text, m, "AMOUNT", val, currency=currency))
        return found

    def _extract_bogo(self, text: str) -> List[Offer]:
        return [self._make_offer(text, m, "BOGO") for m in self.bogo_pattern.finditer(text)]

    def _extract_shipping(self, text: str) -> List[Offer]:
        return [self._make_offer(text, m, "FREE_SHIP") for m in self.free_ship_pattern.finditer(text)]

    def _make_offer(self, text, match, type_str, value=None, currency=None, is_up_to=False):
        """Factory to create clean Offer objects."""
        start, end = match.span()
        # Grab a snippet of text for human review (context)
        context_text = text[max(0, start-15):min(len(text), end+15)].strip()
        
        return Offer(
            discount_type=type_str,
            value=value,
            currency=currency,
            is_up_to=is_up_to,
            offer_text=context_text,
            span=(start, end)
        )

    def _find_nearest(self, target_span, candidates, max_dist=150):
        """
        Calculates physical distance between text spans.
        Returns the candidate if it is within 'max_dist' characters.
        """
        if not candidates: return None
        
        target_mid = (target_span[0] + target_span[1]) / 2
        best_cand = None
        min_dist = float('inf')

        for cand in candidates:
            cand_mid = (cand['span'][0] + cand['span'][1]) / 2
            dist = abs(target_mid - cand_mid)
            
            if dist < min_dist and dist <= max_dist:
                min_dist = dist
                best_cand = cand
        
        return best_cand

    def _map_currency(self, symbol):
        return {'$': 'USD', '€': 'EUR', '£': 'GBP'}.get(symbol, 'USD')

# --- Usage Example ---
if __name__ == "__main__":
    email_sample = """
    Black Friday Alert!
    
    1. Save $20 on all Jackets using code: JACKET20.
    2. Looking for shoes? Take 15% off everything (orders over $50).
    3. Spend $100+ to get Free Shipping.
    
    (Note: Total cart value must be calculated before tax)
    """
    
    extractor = OfferExtractor()
    results = extractor.extract(email_sample)
    
    print(f"Found {len(results)} offers:\n")
    for offer in results:
        print(offer.to_dict())