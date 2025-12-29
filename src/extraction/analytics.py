"""
Analytics module for offer extraction data.
Provides functions to query offers filtered by industry and ISO week.
"""

import sys
import os
from typing import List, Dict, Optional, Tuple
from decimal import Decimal

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Database.dbconnection import DBConnection


def get_weekly_offers_by_industry(
    iso_year: int,
    iso_week: Optional[int] = None,
    industry: Optional[str] = None,
    use_db_prefix: bool = False
) -> List[Dict]:
    """
    Get offers for a specific week, optionally filtered by industry.
    
    Args:
        iso_year: ISO year (e.g., 2025)
        iso_week: Optional ISO week (1-52). If None, returns all weeks in year.
        industry: Optional industry name to filter by (checks primary, secondary, tertiary)
        use_db_prefix: If True, use DB_* environment variables
        
    Returns:
        List of offer dictionaries with company and time information
    """
    db = DBConnection(use_db_prefix=use_db_prefix)
    try:
        conn, cursor = db.connect()
        
        where_clauses = ["et.iso_year = %s"]
        params = [iso_year]
        
        if iso_week:
            where_clauses.append("et.iso_week = %s")
            params.append(iso_week)
        
        if industry:
            where_clauses.append("""
                (c.primary_industry = %s 
                 OR c.secondary_industry = %s 
                 OR c.tertiary_industry = %s)
            """)
            params.extend([industry, industry, industry])
        
        where_sql = " AND ".join(where_clauses)
        
        sql = f"""
            SELECT 
                eo.offer_id,
                eo.email_id,
                eo.discount_type,
                eo.percent_off,
                eo.amount_off,
                eo.currency,
                eo.is_up_to,
                eo.min_spend,
                eo.promo_code,
                eo.confidence,
                eo.offer_text,
                et.iso_year,
                et.iso_week,
                et.week_start_date,
                c.company_id,
                c.company_name,
                c.primary_industry,
                c.secondary_industry,
                c.tertiary_industry,
                c.size_category,
                e.received_datetime
            FROM email_offers eo
            JOIN email_time et ON eo.email_id = et.email_id
            JOIN emails e ON eo.email_id = e.email_id
            JOIN companies c ON e.company_id = c.company_id
            WHERE {where_sql}
            ORDER BY et.iso_week, eo.percent_off DESC NULLS LAST, eo.amount_off DESC NULLS LAST
        """
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        # Convert to list of dictionaries
        offers = []
        for row in rows:
            offers.append({
                "offer_id": row[0],
                "email_id": row[1],
                "discount_type": row[2],
                "percent_off": float(row[3]) if row[3] else None,
                "amount_off": float(row[4]) if row[4] else None,
                "currency": row[5],
                "is_up_to": row[6],
                "min_spend": float(row[7]) if row[7] else None,
                "promo_code": row[8],
                "confidence": float(row[9]) if row[9] else None,
                "offer_text": row[10],
                "iso_year": row[11],
                "iso_week": row[12],
                "week_start_date": row[13],
                "company_id": row[14],
                "company_name": row[15],
                "primary_industry": row[16],
                "secondary_industry": row[17],
                "tertiary_industry": row[18],
                "size_category": row[19],
                "received_datetime": row[20]
            })
        
        return offers
    finally:
        db.close()


def get_best_offers_per_week(
    iso_year: int,
    top_n: int = 10,
    industry: Optional[str] = None,
    use_db_prefix: bool = False,
    include_other_types: bool = False,
    iso_week: Optional[int] = None
) -> List[Dict]:
    """
    Get top N offers per week, optionally filtered by industry.
    
    Args:
        iso_year: ISO year (e.g., 2025)
        top_n: Number of top offers per week (default 10)
        industry: Optional industry name to filter by
        use_db_prefix: If True, use DB_* environment variables
        include_other_types: If True, include FREE_SHIP and BOGO offers
        iso_week: Optional ISO week (1-52) to filter by specific week
        
    Returns:
        List of offer dictionaries, ranked by discount value within each week
    """
    db = DBConnection(use_db_prefix=use_db_prefix)
    try:
        conn, cursor = db.connect()
        
        industry_filter = ""
        week_filter = ""
        params = [iso_year]
        
        if industry:
            industry_filter = """
                AND (c.primary_industry = %s 
                     OR c.secondary_industry = %s 
                     OR c.tertiary_industry = %s)
            """
            params.extend([industry, industry, industry])
        
        if iso_week:
            week_filter = " AND et.iso_week = %s"
            params.append(iso_week)
        
        # Build discount type filter
        if include_other_types:
            discount_type_filter = "eo.discount_type IN ('PERCENT', 'AMOUNT', 'FREE_SHIP', 'BOGO')"
        else:
            discount_type_filter = "eo.discount_type IN ('PERCENT', 'AMOUNT')"
        
        params.append(top_n)
        
        sql = f"""
            WITH weekly_offers AS (
                SELECT 
                    eo.offer_id,
                    eo.email_id,
                    eo.discount_type,
                    eo.percent_off,
                    eo.amount_off,
                    eo.currency,
                    eo.is_up_to,
                    eo.min_spend,
                    eo.promo_code,
                    eo.confidence,
                    eo.offer_text,
                    et.iso_year,
                    et.iso_week,
                    et.week_start_date,
                    c.company_id,
                    c.company_name,
                    c.primary_industry,
                    c.secondary_industry,
                    c.tertiary_industry,
                    c.size_category,
                    e.received_datetime,
                    ROW_NUMBER() OVER (
                        PARTITION BY et.iso_year, et.iso_week
                        ORDER BY 
                            CASE 
                                WHEN eo.discount_type = 'PERCENT' AND eo.percent_off IS NOT NULL 
                                THEN eo.percent_off 
                                WHEN eo.discount_type = 'FREE_SHIP' THEN 999
                                WHEN eo.discount_type = 'BOGO' THEN 998
                                ELSE 0 
                            END DESC,
                            CASE 
                                WHEN eo.discount_type = 'AMOUNT' AND eo.amount_off IS NOT NULL 
                                THEN eo.amount_off 
                                ELSE 0 
                            END DESC
                    ) AS week_rank
                FROM email_offers eo
                JOIN email_time et ON eo.email_id = et.email_id
                JOIN emails e ON eo.email_id = e.email_id
                JOIN companies c ON e.company_id = c.company_id
                WHERE et.iso_year = %s
                    AND {discount_type_filter}
                    {industry_filter}
                    {week_filter}
            )
            SELECT * FROM weekly_offers 
            WHERE week_rank <= %s
            ORDER BY iso_week, week_rank
        """
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        # Convert to list of dictionaries
        offers = []
        for row in rows:
            offers.append({
                "offer_id": row[0],
                "email_id": row[1],
                "discount_type": row[2],
                "percent_off": float(row[3]) if row[3] else None,
                "amount_off": float(row[4]) if row[4] else None,
                "currency": row[5],
                "is_up_to": row[6],
                "min_spend": float(row[7]) if row[7] else None,
                "promo_code": row[8],
                "confidence": float(row[9]) if row[9] else None,
                "offer_text": row[10],
                "iso_year": row[11],
                "iso_week": row[12],
                "week_start_date": row[13],
                "company_id": row[14],
                "company_name": row[15],
                "primary_industry": row[16],
                "secondary_industry": row[17],
                "tertiary_industry": row[18],
                "size_category": row[19],
                "received_datetime": row[20],
                "week_rank": row[21]
            })
        
        return offers
    finally:
        db.close()


def get_industry_summary(
    iso_year: int,
    industry: Optional[str] = None,
    use_db_prefix: bool = False
) -> Dict:
    """
    Get summary statistics for offers, optionally filtered by industry.
    
    Args:
        iso_year: ISO year (e.g., 2025)
        industry: Optional industry name to filter by
        use_db_prefix: If True, use DB_* environment variables
        
    Returns:
        Dictionary with summary statistics
    """
    db = DBConnection(use_db_prefix=use_db_prefix)
    try:
        conn, cursor = db.connect()
        
        industry_filter = ""
        params = [iso_year]
        
        if industry:
            industry_filter = """
                AND (c.primary_industry = %s 
                     OR c.secondary_industry = %s 
                     OR c.tertiary_industry = %s)
            """
            params = [iso_year, industry, industry, industry]
        
        sql = f"""
            SELECT 
                COUNT(DISTINCT eo.offer_id) AS total_offers,
                COUNT(DISTINCT eo.email_id) AS emails_with_offers,
                COUNT(DISTINCT et.iso_week) AS weeks_with_offers,
                AVG(eo.percent_off) AS avg_percent_off,
                MAX(eo.percent_off) AS max_percent_off,
                MIN(eo.percent_off) AS min_percent_off,
                AVG(eo.amount_off) AS avg_amount_off,
                MAX(eo.amount_off) AS max_amount_off,
                COUNT(CASE WHEN eo.discount_type = 'PERCENT' THEN 1 END) AS percent_offers,
                COUNT(CASE WHEN eo.discount_type = 'AMOUNT' THEN 1 END) AS amount_offers,
                COUNT(CASE WHEN eo.discount_type = 'FREE_SHIP' THEN 1 END) AS free_ship_offers
            FROM email_offers eo
            JOIN email_time et ON eo.email_id = et.email_id
            JOIN emails e ON eo.email_id = e.email_id
            JOIN companies c ON e.company_id = c.company_id
            WHERE et.iso_year = %s
                {industry_filter}
        """
        
        cursor.execute(sql, params)
        row = cursor.fetchone()
        
        if row:
            return {
                "total_offers": row[0] or 0,
                "emails_with_offers": row[1] or 0,
                "weeks_with_offers": row[2] or 0,
                "avg_percent_off": float(row[3]) if row[3] else None,
                "max_percent_off": float(row[4]) if row[4] else None,
                "min_percent_off": float(row[5]) if row[5] else None,
                "avg_amount_off": float(row[6]) if row[6] else None,
                "max_amount_off": float(row[7]) if row[7] else None,
                "percent_offers": row[8] or 0,
                "amount_offers": row[9] or 0,
                "free_ship_offers": row[10] or 0
            }
        else:
            return {}
    finally:
        db.close()


def get_weekly_aggregation(
    iso_year: int,
    industry: Optional[str] = None,
    use_db_prefix: bool = False
) -> List[Dict]:
    """
    Get weekly aggregation statistics grouped by ISO week and optionally industry.
    
    Args:
        iso_year: ISO year (e.g., 2025)
        industry: Optional industry name to filter by
        use_db_prefix: If True, use DB_* environment variables
        
    Returns:
        List of dictionaries with weekly stats
    """
    db = DBConnection(use_db_prefix=use_db_prefix)
    try:
        conn, cursor = db.connect()
        
        industry_filter = ""
        group_by_industry = ""
        params = [iso_year]
        
        if industry:
            industry_filter = """
                AND (c.primary_industry = %s 
                     OR c.secondary_industry = %s 
                     OR c.tertiary_industry = %s)
            """
            params = [iso_year, industry, industry, industry]
        else:
            # If no industry filter, group by primary_industry
            group_by_industry = ", c.primary_industry"
        
        sql = f"""
            SELECT 
                et.iso_week,
                c.primary_industry,
                COUNT(DISTINCT eo.offer_id) AS total_offers,
                COUNT(DISTINCT eo.email_id) AS emails_with_offers,
                AVG(eo.percent_off) AS avg_percent_off,
                MAX(eo.percent_off) AS max_percent_off,
                MIN(eo.percent_off) AS min_percent_off,
                COUNT(CASE WHEN eo.discount_type = 'PERCENT' THEN 1 END) AS percent_offers
            FROM email_offers eo
            JOIN email_time et ON eo.email_id = et.email_id
            JOIN emails e ON eo.email_id = e.email_id
            JOIN companies c ON e.company_id = c.company_id
            WHERE et.iso_year = %s
                {industry_filter}
            GROUP BY et.iso_week{group_by_industry}
            ORDER BY et.iso_week, c.primary_industry
        """
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        
        # Convert to list of dictionaries
        results = []
        for row in rows:
            results.append({
                "iso_week": row[0],
                "primary_industry": row[1],
                "total_offers": row[2] or 0,
                "emails_with_offers": row[3] or 0,
                "avg_percent_off": float(row[4]) if row[4] else None,
                "max_percent_off": float(row[5]) if row[5] else None,
                "min_percent_off": float(row[6]) if row[6] else None,
                "percent_offers": row[7] or 0
            })
        
        return results
    finally:
        db.close()


def get_available_industries(use_db_prefix: bool = False) -> List[str]:
    """
    Get list of all available industries from companies table.
    
    Args:
        use_db_prefix: If True, use DB_* environment variables
        
    Returns:
        List of unique industry names (from primary, secondary, tertiary)
    """
    db = DBConnection(use_db_prefix=use_db_prefix)
    try:
        conn, cursor = db.connect()
        
        sql = """
            SELECT DISTINCT industry
            FROM (
                SELECT primary_industry AS industry FROM companies WHERE primary_industry IS NOT NULL
                UNION
                SELECT secondary_industry AS industry FROM companies WHERE secondary_industry IS NOT NULL
                UNION
                SELECT tertiary_industry AS industry FROM companies WHERE tertiary_industry IS NOT NULL
            ) AS all_industries
            WHERE industry IS NOT NULL AND industry != ''
            ORDER BY industry
        """
        
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        return [row[0] for row in rows]
    finally:
        db.close()

