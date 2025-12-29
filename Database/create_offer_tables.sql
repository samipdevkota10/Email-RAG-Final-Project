-- Migration: Create email_offers and etl_runs tables for offer extraction pipeline
-- Run this script to set up the offer extraction infrastructure

-- Create email_offers table (core fact table for extracted offers)
-- Note: Foreign key constraint added separately to handle type matching
CREATE TABLE IF NOT EXISTS email_offers (
  offer_id        BIGSERIAL PRIMARY KEY,
  email_id        INTEGER NOT NULL,

  discount_type   TEXT,        -- PERCENT | AMOUNT | FREE_SHIP | BOGO | OTHER
  percent_off     NUMERIC(6,2),
  amount_off      NUMERIC(10,2),
  currency        TEXT,
  is_up_to        BOOLEAN DEFAULT FALSE,
  min_spend       NUMERIC(10,2),
  promo_code      TEXT,

  offer_text      TEXT,        -- exact extracted span for auditing
  confidence      NUMERIC(4,3) DEFAULT 1.0,

  created_at      TIMESTAMPTZ DEFAULT now()
);

-- Add foreign key constraint (run separately if needed)
-- DO $$
-- BEGIN
--     IF NOT EXISTS (
--         SELECT 1 FROM pg_constraint 
--         WHERE conname = 'email_offers_email_id_fkey'
--     ) THEN
--         ALTER TABLE email_offers
--         ADD CONSTRAINT email_offers_email_id_fkey
--         FOREIGN KEY (email_id) 
--         REFERENCES emails(email_id) 
--         ON DELETE CASCADE;
--     END IF;
-- END $$;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_email_offers_email_id ON email_offers(email_id);
CREATE INDEX IF NOT EXISTS idx_email_offers_discount_type ON email_offers(discount_type);
CREATE INDEX IF NOT EXISTS idx_email_offers_created_at ON email_offers(created_at);

-- Create etl_runs table (pipeline state tracking)
CREATE TABLE IF NOT EXISTS etl_runs (
  pipeline        TEXT PRIMARY KEY,
  last_email_id   INT,
  updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Add comments for documentation
COMMENT ON TABLE email_offers IS 'Stores normalized offers extracted from emails. Multiple offers per email allowed.';
COMMENT ON COLUMN email_offers.offer_text IS 'Exact extracted text span for audit/debugging purposes';
COMMENT ON COLUMN email_offers.confidence IS 'Confidence score 0.0-1.0. 1.0 for regex matches, lower for LLM extraction.';
COMMENT ON TABLE etl_runs IS 'Tracks ETL pipeline progress for resumable batch processing';

