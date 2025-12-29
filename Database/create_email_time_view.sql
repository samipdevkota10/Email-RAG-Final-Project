-- Migration: Create email_time view for ISO week-based analytics
-- This view maps emails to ISO weeks and includes company_id for industry filtering

CREATE OR REPLACE VIEW email_time AS
SELECT 
  e.email_id,
  e.company_id,
  e.received_datetime,
  EXTRACT(ISOYEAR FROM e.received_datetime)::INT AS iso_year,
  EXTRACT(WEEK FROM e.received_datetime)::INT AS iso_week,
  DATE_TRUNC('week', e.received_datetime) AS week_start_date
FROM emails e
WHERE e.received_datetime IS NOT NULL;

-- Add comment for documentation
COMMENT ON VIEW email_time IS 'Maps emails to ISO weeks for time-based analytics. Includes company_id for industry filtering.';

