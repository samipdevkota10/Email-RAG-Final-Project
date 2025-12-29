import json
import logging
import threading
from functools import wraps
from typing import List, Optional, Dict, Any
from datetime import datetime
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# Shared resources
from src.database import AnalyticsPool
from src.config import settings
from src.ai import client

log = logging.getLogger("emaillens.analytics")

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# ==============================================================================
# CACHING UTILS (Thread-Safe)
# ==============================================================================
_CACHE: Dict[str, tuple] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 300  # 5 minutes

def _has_companies_table() -> bool:
    """Detect once (cached) if companies table exists."""
    key = "has_companies"
    now = time.time()
    
    with _CACHE_LOCK:
        if key in _CACHE:
            val, ts = _CACHE[key]
            if now - ts < _CACHE_TTL:
                return bool(val)
    
    try:
        with AnalyticsPool.get_cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'companies');"
            )
            row = cur.fetchone()
            exists = bool(row and row[0])
            with _CACHE_LOCK:
                _CACHE[key] = (exists, now)
            return exists
    except Exception as e:
        log.warning(f"Failed to check companies table: {e}")
        with _CACHE_LOCK:
            _CACHE[key] = (False, now)
        return False

def _get_cached(key: str):
    """Thread-safe cache get."""
    now = time.time()
    with _CACHE_LOCK:
        if key in _CACHE:
            data, ts = _CACHE[key]
            if now - ts < _CACHE_TTL:
                return data
    return None

def _set_cached(key: str, value: Any):
    """Thread-safe cache set."""
    with _CACHE_LOCK:
        _CACHE[key] = (value, time.time())

# ==============================================================================
# PYDANTIC MODELS
# ==============================================================================

class HeadlineStats(BaseModel):
    total_active_offers: int
    avg_market_discount: float
    top_industry: Optional[str] = None

class DiscountBucket(BaseModel):
    bucket_label: str
    bucket_min: int = 0
    bucket_max: int = 100
    count: int
    percentage: float
    avg_in_bucket: Optional[float] = None
    example_values: Optional[List[float]] = None

class DiscountDistribution(BaseModel):
    total_offers: int
    avg_discount: float
    median_discount: Optional[float] = None
    min_discount: float
    max_discount: float
    std_dev: Optional[float] = None
    buckets: List[DiscountBucket]

class WeeklyStat(BaseModel):
    week: int
    avg_discount: float
    offer_count: int
    wow_change: Optional[float] = None

class AnalyticsOffer(BaseModel):
    offer_id: int
    discount_type: Optional[str]
    percent_off: Optional[float]
    amount_off: Optional[float]
    currency: Optional[str] = "USD"
    is_up_to: bool
    min_spend: Optional[float]
    promo_code: Optional[str]
    offer_text: Optional[str]
    confidence: Optional[float]
    
    email_id: int
    snippet_text: Optional[str]
    from_name: Optional[str]
    received_datetime: str
    body_html: Optional[str]
    
    company_name: Optional[str]
    primary_industry: Optional[str]
    secondary_industry: Optional[str]
    
    iso_year: Optional[int]
    iso_week: Optional[int]
    week_rank: Optional[int]

class OffersResponse(BaseModel):
    success: bool
    count: int
    offers: List[AnalyticsOffer]

class OffersRequest(BaseModel):
    year: int = Field(2025, ge=2020, le=2030)
    week: Optional[int] = Field(None, ge=1, le=53)
    industry: Optional[str] = None
    top_n: int = Field(50, ge=1, le=500)
    sort_by: str = "week"
    include_other_types: bool = False

class SummaryRequest(BaseModel):
    year: int = 2025
    week: Optional[int] = None
    industry: Optional[str] = None
    offer_ids: Optional[List[int]] = None

class SummaryResponse(BaseModel):
    summary: str
    citations: List[int]

# ==============================================================================
# OPTIMIZED QUERY BUILDER
# ==============================================================================

def _build_filter_sql(year: int, week: Optional[int], industry: Optional[str], include_others: bool = True):
    """
    Builds optimized SQL clauses.
    Critically uses DATE RANGES instead of EXTRACT() to hit the index.
    """
    # 1. Date Range Optimization (Index Friendly)
    start_date = f"{year}-01-01"
    end_date = f"{year + 1}-01-01"
    
    filters = ["e.received_datetime >= %s AND e.received_datetime < %s"]
    args = [start_date, end_date]
    
    # 2. Week Filtering
    if week:
        filters.append("EXTRACT(WEEK FROM e.received_datetime)::INT = %s")
        args.append(week)
        
    # 3. Industry Filtering (only if companies table exists)
    # Use ILIKE for case-insensitive matching since dropdown shows INITCAP formatted values
    if industry and _has_companies_table():
        filters.append("""
            (INITCAP(TRIM(c.primary_industry)) ILIKE %s OR 
             INITCAP(TRIM(c.secondary_industry)) ILIKE %s)
        """)
        args.extend([industry, industry])

    # 4. Offer Type Filtering
    if not include_others:
        filters.append("eo.discount_type IN ('PERCENT', 'AMOUNT')")
    else:
        filters.append("eo.discount_type != 'NO_OFFER'")

    return " AND ".join(filters), args

# ==============================================================================
# ENDPOINTS
# ==============================================================================

@router.get("/industries")
def get_industries():
    """
    Returns clean list of industries. Cached for 5 minutes.
    """
    cache_key = "industries_list"
    cached = _get_cached(cache_key)
    if cached is not None:
        return {"industries": cached}
    
    if not _has_companies_table():
        _set_cached(cache_key, [])
        return {"industries": []}
    
    try:
        with AnalyticsPool.get_cursor() as cur:
            sql = """
                SELECT DISTINCT INITCAP(TRIM(primary_industry)) as ind
                FROM companies 
                WHERE primary_industry IS NOT NULL 
                  AND TRIM(primary_industry) != ''
                  AND primary_industry NOT ILIKE 'nan'
                ORDER BY 1 ASC
            """
            cur.execute(sql)
            industries = [r[0] for r in cur.fetchall() if r[0]]
            _set_cached(cache_key, industries)
            return {"industries": industries}
    except Exception as e:
        log.error(f"Industries fetch error: {e}")
        return {"industries": []}

@router.get("/stats/headline", response_model=HeadlineStats)
def get_headline_stats(year: int = 2025):
    """
    Fast aggregation for dashboard headers.
    """
    # Use same date range optimization
    start = f"{year}-01-01"
    end = f"{year+1}-01-01"
    has_comp = _has_companies_table()
    
    # Use INITCAP for consistent formatting, filter out NaN/empty
    top_industry_sql = """
        MODE() WITHIN GROUP (ORDER BY INITCAP(TRIM(c.primary_industry))) 
        FILTER (WHERE c.primary_industry IS NOT NULL 
                AND TRIM(c.primary_industry) != '' 
                AND c.primary_industry NOT ILIKE 'nan') as top_industry
    """ if has_comp else "NULL as top_industry"
    join_comp = "LEFT JOIN companies c ON e.company_id = c.company_id" if has_comp else ""

    sql = f"""
        SELECT 
            COUNT(*) as total_offers,
            ROUND(AVG(CASE WHEN discount_type = 'PERCENT' THEN percent_off END), 1) as avg_discount,
            {top_industry_sql}
        FROM email_offers eo
        JOIN emails e ON eo.email_id = e.email_id
        {join_comp}
        WHERE e.received_datetime >= %s AND e.received_datetime < %s
          AND eo.discount_type != 'NO_OFFER'
    """
    with AnalyticsPool.get_cursor() as cur:
        cur.execute(sql, (start, end))
        row = cur.fetchone()
    
    return HeadlineStats(
        total_active_offers=row[0] or 0,
        avg_market_discount=float(row[1]) if row[1] else 0.0,
        top_industry=row[2] if has_comp and row[2] else None
    )

@router.get("/stats/distributions", response_model=DiscountDistribution)
def get_discount_distribution(year: int = 2025, industry: Optional[str] = None):
    """
    Enhanced histogram data with statistics for bar charts.
    """
    has_comp = _has_companies_table()
    where_sql, args = _build_filter_sql(year, None, industry if has_comp else None, False)
    
    join_comp = "LEFT JOIN companies c ON e.company_id = c.company_id" if has_comp else ""

    # Get overall stats first
    stats_sql = f"""
        SELECT 
            COUNT(*) as total,
            ROUND(AVG(percent_off)::numeric, 1) as avg_discount,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY percent_off) as median_discount,
            MIN(percent_off) as min_discount,
            MAX(percent_off) as max_discount,
            ROUND(STDDEV(percent_off)::numeric, 1) as std_dev
        FROM email_offers eo
        JOIN emails e ON eo.email_id = e.email_id
        {join_comp}
        WHERE {where_sql} AND eo.discount_type = 'PERCENT' AND percent_off IS NOT NULL
    """
    
    # Get bucket distribution with avg per bucket
    bucket_sql = f"""
        SELECT 
            width_bucket(percent_off, 0, 100, 10) as bucket,
            COUNT(*) as cnt,
            ROUND(AVG(percent_off)::numeric, 1) as avg_in_bucket
        FROM email_offers eo
        JOIN emails e ON eo.email_id = e.email_id
        {join_comp}
        WHERE {where_sql} AND eo.discount_type = 'PERCENT' AND percent_off IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """
    
    with AnalyticsPool.get_cursor() as cur:
        # Get overall stats
        cur.execute(stats_sql, args)
        stats_row = cur.fetchone()
        
        # Get bucket data
        cur.execute(bucket_sql, args)
        bucket_rows = cur.fetchall()
    
    total = stats_row[0] or 0
    avg_discount = float(stats_row[1]) if stats_row[1] else 0.0
    median_discount = float(stats_row[2]) if stats_row[2] else None
    min_discount = float(stats_row[3]) if stats_row[3] else 0.0
    max_discount = float(stats_row[4]) if stats_row[4] else 0.0
    std_dev = float(stats_row[5]) if stats_row[5] else None
    
    buckets = []
    for b_id, count, avg_in_bucket in bucket_rows:
        if b_id is None: 
            continue
        start = (b_id - 1) * 10
        buckets.append(DiscountBucket(
            bucket_label=f"{start}-{start+10}%",
            bucket_min=start,
            bucket_max=start + 10,
            count=count,
            percentage=round((count / total * 100), 1) if total else 0,
            avg_in_bucket=float(avg_in_bucket) if avg_in_bucket else None
        ))
        
    return DiscountDistribution(
        total_offers=total,
        avg_discount=avg_discount,
        median_discount=median_discount,
        min_discount=min_discount,
        max_discount=max_discount,
        std_dev=std_dev,
        buckets=buckets
    )

@router.get("/trends", response_model=List[WeeklyStat])
def get_trends(year: int = 2025, industry: Optional[str] = None):
    """
    Trend line data with Week-Over-Week calculation.
    """
    has_comp = _has_companies_table()
    where_sql, args = _build_filter_sql(year, None, industry if has_comp else None, False)
    join_comp = "LEFT JOIN companies c ON e.company_id = c.company_id" if has_comp else ""
    
    sql = f"""
        WITH weekly AS (
            SELECT 
                EXTRACT(WEEK FROM e.received_datetime)::INT as week_num,
                AVG(eo.percent_off) as avg_discount,
                COUNT(*) as volume
            FROM email_offers eo
            JOIN emails e ON eo.email_id = e.email_id
            {join_comp}
            WHERE {where_sql} AND eo.discount_type = 'PERCENT'
            GROUP BY 1
        )
        SELECT 
            week_num,
            ROUND(avg_discount, 1),
            volume,
            ROUND((avg_discount - LAG(avg_discount) OVER (ORDER BY week_num))::numeric, 1) as wow
        FROM weekly
        ORDER BY week_num ASC
    """
    
    with AnalyticsPool.get_cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
        
    return [
        WeeklyStat(week=r[0], avg_discount=float(r[1]), offer_count=r[2], wow_change=float(r[3]) if r[3] else 0.0)
        for r in rows
    ]

@router.post("/offers", response_model=OffersResponse)
def get_best_offers(req: OffersRequest):
    """
    Main feed. Uses SINGLE query optimization + Index-friendly date filters.
    """
    has_comp = _has_companies_table()
    where_sql, args = _build_filter_sql(req.year, req.week, req.industry if has_comp else None, req.include_other_types)

    # Dynamic Sort
    if req.sort_by == "percent":
        order = "eo.percent_off DESC NULLS LAST"
    elif req.sort_by == "amount":
        order = "eo.amount_off DESC NULLS LAST"
    else:
        order = "e.received_datetime DESC"

    sql = f"""
        SELECT 
            eo.offer_id, eo.discount_type, eo.percent_off, eo.amount_off, 
            eo.currency, eo.is_up_to, eo.min_spend, eo.promo_code, eo.offer_text, eo.confidence,
            e.email_id, e.snippet_text, e.from_name, e.received_datetime, e.body_html,
            { "c.company_name, c.primary_industry, c.secondary_industry," if has_comp else "NULL as company_name, NULL as primary_industry, NULL as secondary_industry," }
            EXTRACT(ISOYEAR FROM e.received_datetime)::INT as iso_year,
            EXTRACT(WEEK FROM e.received_datetime)::INT as iso_week,
            ROW_NUMBER() OVER (
                PARTITION BY EXTRACT(WEEK FROM e.received_datetime)::INT 
                ORDER BY eo.percent_off DESC NULLS LAST
            ) as week_rank
        FROM email_offers eo
        JOIN emails e ON eo.email_id = e.email_id
        { "LEFT JOIN companies c ON e.company_id = c.company_id" if has_comp else "" }
        WHERE {where_sql}
        ORDER BY {order}
        LIMIT %s
    """
    args.append(req.top_n)

    with AnalyticsPool.get_cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()

    offers = []
    for r in rows:
        offers.append(AnalyticsOffer(
            offer_id=r[0], discount_type=r[1], 
            percent_off=float(r[2]) if r[2] is not None else None,
            amount_off=float(r[3]) if r[3] is not None else None,
            currency=r[4], is_up_to=r[5], 
            min_spend=float(r[6]) if r[6] is not None else None,
            promo_code=r[7], offer_text=r[8], confidence=float(r[9]) if r[9] else None,
            email_id=r[10], snippet_text=r[11] or "", 
            from_name=r[12], received_datetime=str(r[13]), body_html=r[14],
            company_name=r[15], primary_industry=r[16], secondary_industry=r[17],
            iso_year=r[18], iso_week=r[19], week_rank=r[20]
        ))

    return OffersResponse(
        success=True,
        count=len(offers),
        offers=offers
    )

@router.post("/summary", response_model=SummaryResponse)
def generate_summary(req: SummaryRequest):
    """
    AI Insight generator. Uses IDs to ensure consistency with view.
    """
    if not req.offer_ids:
        return SummaryResponse(summary="Select data to analyze.", citations=[])

    has_comp = _has_companies_table()
    comp_cols = "c.company_name, c.primary_industry" if has_comp else "NULL as company_name, NULL as primary_industry"
    comp_join = "LEFT JOIN companies c ON e.company_id = c.company_id" if has_comp else ""

    sql = """
        SELECT 
            eo.offer_id, eo.discount_type, eo.percent_off, eo.amount_off, eo.promo_code,
            {comp_cols}
        FROM email_offers eo
        JOIN emails e ON eo.email_id = e.email_id
        {comp_join}
        WHERE eo.offer_id = ANY(%s)
    """.format(comp_cols=comp_cols, comp_join=comp_join)
    
    with AnalyticsPool.get_cursor() as cur:
        cur.execute(sql, (req.offer_ids,))
        rows = cur.fetchall()

    if not rows:
        return SummaryResponse(summary="No matching data found.", citations=[])

    # Compress Context for LLM
    lines = []
    for r in rows[:40]:
        val = f"{r[2]}%" if r[2] else (f"${r[3]}" if r[3] else r[1])
        lines.append(f"- {r[5]} ({r[6]}): {val} {f'[Code: {r[4]}]' if r[4] else ''} (ID: {r[0]})")
    
    prompt = "\n".join(lines)
    
    system = (
        "Retail Analyst AI. Summarize these offers in 3 bullet points. "
        "Focus on: 1. Deepest discounts, 2. Strategy (codes vs auto), 3. Industry trends. "
        "Return JSON: { \"summary\": string, \"citations\": [ids] }"
    )

    try:
        res = client.chat.completions.create(
            model=settings.openai_model_chat,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            timeout=25
        )
        out = json.loads(res.choices[0].message.content or "{}")
        return SummaryResponse(summary=out.get("summary", "Analysis done."), citations=out.get("citations", []))
    except Exception as e:
        log.error(f"LLM Error: {e}")
        return SummaryResponse(summary="Analysis unavailable.", citations=[])