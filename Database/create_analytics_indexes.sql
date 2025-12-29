-- ==============================================================================
-- Analytics Performance Indexes (email_offers table ONLY)
-- Run this against the AWS database (backstroke_email_db)
-- ==============================================================================

-- Critical: email_offers.email_id for JOINs to emails table
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_offers_email_id 
    ON email_offers(email_id);

-- Discount type filtering (PERCENT, AMOUNT, FREE_SHIP, BOGO, NO_OFFER)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_offers_discount_type 
    ON email_offers(discount_type);

-- Sorting by percent discount (partial index for PERCENT type only)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_offers_percent_off 
    ON email_offers(percent_off DESC NULLS LAST) 
    WHERE discount_type = 'PERCENT';

-- Sorting by dollar amount (partial index for AMOUNT type only)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_offers_amount_off 
    ON email_offers(amount_off DESC NULLS LAST) 
    WHERE discount_type = 'AMOUNT';

-- Composite index for common filtering: discount_type + email_id
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_offers_type_email 
    ON email_offers(discount_type, email_id);

-- Refresh table statistics
ANALYZE email_offers;

