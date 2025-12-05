# src/app.py
from __future__ import annotations

import json
import logging
import os
import random
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field, ConfigDict
from pydantic_settings import BaseSettings
from psycopg2.pool import SimpleConnectionPool  # type: ignore


from src.route.eval import router as eval_router

# --- Bootstrapping ------------------------------------------------------------
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("emaillens")

# --- Settings -----------------------------------------------------------------
class Settings(BaseSettings):
    openai_api_key: str
    cors_origins: List[str] = ["http://localhost:5173"]  # add prod origin later
    openai_model_chat: str = "gpt-4o-mini"
    openai_model_embed: str = "text-embedding-3-small"
    max_llm_chars_body_preview: int = 1500
    max_llm_chars_snippet: int = 500
    default_limit: int = 12
    vector_dim: int = 1536  # for sanity checks (text embeddings)
    database_url: str = Field(..., description="Postgres DSN, e.g. postgres://...")

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore",
    )

settings = Settings()
client = OpenAI(api_key=settings.openai_api_key)

# --- DB connection pool -------------------------------------------------------
DB_POOL: Optional[SimpleConnectionPool] = None


def init_db_pool() -> None:
    """
    Initialize a global psycopg2 connection pool using DATABASE_URL.
    """
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=settings.database_url,
        )
        log.info("Initialized DB connection pool.")


def close_db_pool() -> None:
    global DB_POOL
    if DB_POOL is not None:
        DB_POOL.closeall()
        DB_POOL = None
        log.info("Closed DB connection pool.")


@contextmanager
def db_session():
    """
    Context manager yielding (conn, cursor) from the global pool.
    Only used for read-only queries in this app.
    """
    if DB_POOL is None:
        raise RuntimeError("DB pool not initialized")
    conn = DB_POOL.getconn()
    try:
        with conn.cursor() as cur:
            yield conn, cur
    finally:
        DB_POOL.putconn(conn)


def test_connection() -> bool:
    try:
        with db_session() as (_, cursor):
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


def get_date_range() -> tuple:
    with db_session() as (_, cursor):
        cursor.execute("SELECT MIN(received_datetime), MAX(received_datetime), COUNT(*) FROM emails")
        return cursor.fetchone() or (None, None, 0)


# --- Helpers: embeddings & math ----------------------------------------------
def _normalize(v: List[float]) -> List[float]:
    n = (sum(x * x for x in v) ** 0.5) or 1.0
    return [x / n for x in v]


@lru_cache(maxsize=256)
def _embed_query_unit(text: str) -> List[float]:
    """
    Query embedding with simple LRU cache to avoid recomputing identical queries.
    """
    v = client.embeddings.create(model=settings.openai_model_embed, input=[text]).data[0].embedding
    return _normalize(v)


def _to_vec_sql(v: List[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


def rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def mmr_select(
    ids: List[int],
    qvec: Optional[List[float]],
    embed_lookup: Dict[int, List[float]],
    k: int,
    lambda_: float = 0.3,
) -> List[int]:
    """
    Maximal Marginal Relevance selection over candidate ids with preloaded embeddings.
    If qvec is None, this will just return the first k ids (no embeddings available).
    """
    if qvec is None:
        return ids[:k]

    selected: List[int] = []
    remaining = set(ids)

    # cosine similarity between two unit vectors
    def cos(a: List[float], b: List[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    while remaining and len(selected) < k:
        best_id = None
        best_score = -1e9
        for eid in list(remaining):
            evec = embed_lookup.get(eid)
            if not evec:
                rel = 0.0
            else:
                rel = cos(qvec, evec)  # relevance to query
            if not selected:
                score = rel
            else:
                max_sim = max(cos(evec, embed_lookup.get(sid, evec)) for sid in selected)
                score = lambda_ * rel - (1.0 - lambda_) * max_sim
            if score > best_score:
                best_score = score
                best_id = eid
        if best_id is None:
            break
        selected.append(best_id)
        remaining.remove(best_id)
    return selected


# --- Models -------------------------------------------------------------------
class EmailSnippet(BaseModel):
    email_id: int
    snippet_text: str
    from_name: Optional[str] = None
    from_address: Optional[str] = None
    received_datetime: Optional[datetime] = None
    body_html: Optional[str] = None


class EmailResponse(BaseModel):
    success: bool
    count: int
    total_count: int
    emails: List[EmailSnippet]
    message: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    start: Optional[date] = None
    end: Optional[date] = None
    include_body: bool = False
    auto_expand: bool = False
    limit: int = Field(10, ge=1, le=100)
    offset: int = Field(0, ge=0)


class SnippetsRequest(BaseModel):
    limit: int = Field(5, ge=1, le=100)
    offset: int = Field(0, ge=0)


class EmailsRequest(BaseModel):
    limit: int = Field(10, ge=1, le=100)
    offset: int = Field(0, ge=0)


class KeywordsRequest(BaseModel):
    limit: int = Field(10, ge=1, le=50)


class VectorSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    start: Optional[date] = None
    end: Optional[date] = None
    limit: int = Field(10, ge=1, le=100)
    offset: int = Field(0, ge=0)


class HybridSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    start: Optional[date] = None
    end: Optional[date] = None
    limit: int = Field(12, ge=1, le=100)
    offset: int = Field(0, ge=0)  # still supported, but we'll top-K then slice
    fts_k: int = Field(100, ge=10, le=500)
    vec_k: int = Field(100, ge=10, le=500)
    mmr_lambda: float = Field(0.3, ge=0.0, le=1.0)  # 0=diversify more, 1=prioritize relevance


class ChatAnswerRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: str = Field("vector", description="vector | keyword | hybrid")
    start: Optional[date] = None
    end: Optional[date] = None
    limit: int = Field(12, ge=1, le=50)
    offset: int = Field(0, ge=0)
    include_body: bool = False  # only used in keyword mode for now
    mmr_lambda: Optional[float] = Field(None, ge=0.0, le=1.0)


class ChatAnswer(BaseModel):
    summary: str
    citations: List[int]
    results: EmailResponse


# --- Small helpers ------------------------------------------------------------
def _compress(text: str, max_chars: int) -> str:
    return (text or "")[:max_chars] + ("…" if text and len(text) > max_chars else "")


def _openai_chat_json(messages, tries: int = 3, timeout: int = 25) -> dict:
    for i in range(tries):
        try:
            resp = client.chat.completions.create(
                model=settings.openai_model_chat,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=messages,
                timeout=timeout,
            )
            content = resp.choices[0].message.content or "{}"
            return json.loads(content)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(0.6 * (2 ** i) + random.random() * 0.3)


def rows_to_snippets(rows: Sequence[tuple]) -> List[EmailSnippet]:
    """
    Convert raw email rows to EmailSnippet list.
    Assumes row order: (email_id, snippet_text, from_name, from_address, received_datetime, body_html).
    """
    return [
        EmailSnippet(
            email_id=r[0],
            snippet_text=r[1] or "No snippet available",
            from_name=r[2],
            from_address=r[3],
            received_datetime=r[4],
            body_html=r[5],
        )
        for r in rows
    ]


def build_date_filters(start: Optional[date], end: Optional[date], alias: str = "e.") -> Tuple[List[str], List[object]]:
    clauses: List[str] = []
    args: List[object] = []
    if start:
        clauses.append(f"{alias}received_datetime >= %s")
        args.append(start)
    if end:
        clauses.append(f"{alias}received_datetime < %s")
        args.append(end + timedelta(days=1))
    return clauses, args


# --- SQL Baseline (keyword) ---------------------------------------------------
def search_emails_sql(
    q: str,
    limit: int = 10,
    offset: int = 0,
    start: Optional[date] = None,
    end: Optional[date] = None,
    include_body: bool = False,
) -> Tuple[List[tuple], int]:
    field_expr = (
        "(COALESCE(header_text,'') || ' ' || COALESCE(snippet_text,'') || ' ' || COALESCE(from_name,''))"
        + (" || ' ' || COALESCE(body_html,'')" if include_body else "")
    )

    where_parts = [f"{field_expr} ILIKE %s"]
    args: List[object] = [f"%{q}%"]

    date_clauses, date_args = build_date_filters(start, end, alias="")
    where_parts.extend(date_clauses)
    args.extend(date_args)

    where_sql = " AND ".join(where_parts)
    sql = f"""
        SELECT email_id, snippet_text, from_name, from_address, received_datetime, body_html,
               COUNT(*) OVER() AS total_count
        FROM emails
        WHERE {where_sql}
        ORDER BY received_datetime DESC NULLS LAST
        LIMIT %s OFFSET %s
    """
    args.extend([limit, offset])

    with db_session() as (_, cursor):
        cursor.execute(sql, args)
        rows = cursor.fetchall()
    total = rows[0][-1] if rows else 0
    return rows, total


# --- Vector search ------------------------------------------------------------
def vector_search_sql(
    q: str,
    limit: int,
    offset: int,
    start: Optional[date],
    end: Optional[date],
) -> Tuple[List[tuple], int]:
    qv = _to_vec_sql(_embed_query_unit(q))
    date_clauses, date_args = build_date_filters(start, end)
    where = ["e.embedding_unit IS NOT NULL"] + date_clauses
    where_sql = " AND ".join(where)

    sql = f"""
        WITH q AS (SELECT %s::vector AS v)
        SELECT e.email_id, e.snippet_text, e.from_name, e.from_address, e.received_datetime, e.body_html,
               1 - (e.embedding_unit <#> q.v) AS cosine_sim,
               COUNT(*) OVER() AS total_count
        FROM emails e, q
        WHERE {where_sql}
        ORDER BY e.embedding_unit <-> q.v
        LIMIT %s OFFSET %s
    """
    args = [qv] + date_args + [limit, offset]
    with db_session() as (_, cur):
        cur.execute(sql, args)
        rows = cur.fetchall()
    total = rows[0][-1] if rows else 0
    return rows, total


# --- Hybrid search (FTS + Vectors + RRF + optional MMR) -----------------------
def hybrid_candidates_fts(
    q: str, k: int, start: Optional[date], end: Optional[date]
) -> List[Tuple[int, float]]:
    """
    Returns list of (email_id, fts_score) ordered by FTS score desc.
    Uses precomputed search_fts tsvector column with a GIN index.
    """
    date_clauses, date_args = build_date_filters(start, end, alias="e.")
    dc = " AND " + " AND ".join(date_clauses) if date_clauses else ""

    sql = f"""
        WITH q AS (SELECT websearch_to_tsquery('english', %s) tsq)
        SELECT e.email_id,
               ts_rank_cd(e.search_fts, q.tsq) AS fts_score
        FROM emails e, q
        WHERE e.search_fts @@ q.tsq
          {dc}
        ORDER BY fts_score DESC
        LIMIT %s
    """
    args: List[object] = [q] + date_args + [k]
    with db_session() as (_, cur):
        cur.execute(sql, args)
        return [(r[0], float(r[1])) for r in cur.fetchall()]


def hybrid_candidates_vec(
    q: str, k: int, start: Optional[date], end: Optional[date]
) -> List[Tuple[int, float]]:
    qv = _to_vec_sql(_embed_query_unit(q))
    date_clauses, date_args = build_date_filters(start, end)
    where = ["e.embedding_unit IS NOT NULL"] + date_clauses
    where_sql = " AND ".join(where)

    sql = f"""
        WITH q AS (SELECT %s::vector AS v)
        SELECT e.email_id, 1 - (e.embedding_unit <#> q.v) AS sim
        FROM emails e, q
        WHERE {where_sql}
        ORDER BY e.embedding_unit <-> q.v
        LIMIT %s
    """
    args = [qv] + date_args + [k]
    with db_session() as (_, cur):
        cur.execute(sql, args)
        return [(r[0], float(r[1])) for r in cur.fetchall()]


def load_embeddings_for(ids: Sequence[int]) -> Dict[int, List[float]]:
    if not ids:
        return {}
    sql = "SELECT email_id, embedding_unit FROM emails WHERE email_id = ANY(%s)"
    with db_session() as (_, cur):
        cur.execute(sql, (list(ids),))
        rows = cur.fetchall()
    out: Dict[int, List[float]] = {}
    for eid, vec in rows:
        if vec is None:
            continue
        out[int(eid)] = list(vec)
    return out


def fetch_emails_by_ids_preserve(ids: Sequence[int]) -> List[tuple]:
    """
    Fetch emails by ids, preserving the order of the input list via array_position.
    """
    if not ids:
        return []
    with db_session() as (_, cur):
        cur.execute(
            """
            SELECT e.email_id, e.snippet_text, e.from_name, e.from_address, e.received_datetime, e.body_html
            FROM emails e
            WHERE e.email_id = ANY(%s)
            ORDER BY array_position(%s::int[], e.email_id)
            """,
            (list(ids), list(ids)),
        )
        rows = cur.fetchall()
    return rows


def hybrid_retrieve_ids(
    query: str,
    start: Optional[date],
    end: Optional[date],
    limit: int,
    offset: int,
    fts_k: int,
    vec_k: int,
    mmr_lambda: float,
) -> Tuple[List[int], int]:
    """
    Shared hybrid retrieval pipeline used by both /search/hybrid and /chat/answer (mode=hybrid).
    """
    # 1) Candidates
    fts = hybrid_candidates_fts(query, fts_k, start, end)  # [(id, fts_score)]
    vec = hybrid_candidates_vec(query, vec_k, start, end)  # [(id, sim)]

    fts_ids = [eid for eid, _ in fts]
    vec_ids = [eid for eid, _ in vec]

    # 2) RRF fusion
    scores: Dict[int, float] = {}
    for i, eid in enumerate(fts_ids, start=1):
        scores[eid] = scores.get(eid, 0.0) + rrf(i)
    for i, eid in enumerate(vec_ids, start=1):
        scores[eid] = scores.get(eid, 0.0) + rrf(i)

    fused_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    # 3) Optional MMR diversification
    embed_lookup = load_embeddings_for(fused_ids[: max(limit * 3, 50)])
    try:
        qvec = _embed_query_unit(query)
    except Exception:
        qvec = None

    diversified = mmr_select(
        fused_ids,
        qvec,
        embed_lookup,
        k=limit + offset,  # get enough for pagination
        lambda_=mmr_lambda,
    )

    ordered_ids = diversified[offset : offset + limit]
    total = len(fused_ids)  # approximate total
    return ordered_ids, total


# --- FastAPI app & middleware -------------------------------------------------
app = FastAPI(
    title="MailLens API",
    description="Keyword, vector, and hybrid search over marketing emails with LLM synthesis.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(eval_router)


@app.on_event("startup")
def on_startup():
    init_db_pool()


@app.on_event("shutdown")
def on_shutdown():
    close_db_pool()


@app.middleware("http")
async def timing_mw(request, call_next):
    t0 = time.perf_counter()
    resp = None
    try:
        resp = await call_next(request)
        return resp
    finally:
        dt = (time.perf_counter() - t0) * 1000
        status = getattr(resp, "status_code", "?") if resp is not None else "?"
        log.info("path=%s status=%s time_ms=%.1f", request.url.path, status, dt)


# --- Endpoints: meta ----------------------------------------------------------
@app.get("/")
async def root():
    return {
        "message": "MailLens API",
        "version": "2.0.0",
        "endpoints": {
            "health": "/health",
            "date_range": "/stats/date-range",
            "search_keyword": "/search (POST)",
            "search_vector": "/search/vector (POST)",
            "search_hybrid": "/search/hybrid (POST)",
            "chat_answer": "/chat/answer (POST)",
            # image endpoints listed below
            "image_text": "/search/image-text (POST)",
            "image_image": "/search/image-image (POST)",
            "image_index_stats": "/stats/image-index (GET)",
        },
        "notes": "Hybrid search uses FTS + vectors with RRF; optional MMR for diversification.",
    }


@app.get("/health")
async def health_check():
    ok = test_connection()
    return {"status": "healthy" if ok else "unhealthy", "database": "connected" if ok else "disconnected"}


@app.get("/stats/date-range")
async def stats_date_range():
    try:
        min_d, max_d, total = get_date_range()
        return {"min_date": min_d, "max_date": max_d, "total_emails": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Endpoints: keyword & vector ---------------------------------------------
@app.post("/search", response_model=EmailResponse)
async def search_emails_endpoint(req: SearchRequest):
    try:
        rows, total = search_emails_sql(
            q=req.query,
            limit=req.limit,
            offset=req.offset,
            start=req.start,
            end=req.end,
            include_body=req.include_body,
        )
        emails = rows_to_snippets(rows)

        if total == 0 and (req.start or req.end):
            min_d, max_d, _ = get_date_range()
            hint = ""
            if min_d and max_d:
                # ensure date() is safe
                hint = f" Dataset span is {min_d.date()} to {max_d.date()}."
            msg = f"No emails matched '{req.query}' between {req.start} and {req.end}.{hint}"
            if req.auto_expand:
                rows2, total2 = search_emails_sql(req.query, req.limit, req.offset, None, None, req.include_body)
                emails2 = rows_to_snippets(rows2)
                return EmailResponse(
                    success=True,
                    count=len(emails2),
                    total_count=total2,
                    emails=emails2,
                    message=f"{msg} Showing {len(emails2)} of {total2} across all dates.",
                )
            return EmailResponse(success=True, count=0, total_count=0, emails=[], message=msg)

        msg = f"Found {len(emails)} of {total} emails matching '{req.query}'"
        if req.start or req.end:
            msg += " within the selected date range"
        return EmailResponse(
            success=True,
            count=len(emails),
            total_count=total,
            emails=emails,
            message=msg,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search/vector", response_model=EmailResponse)
async def vector_search_endpoint(req: VectorSearchRequest):
    try:
        rows, total = vector_search_sql(req.query, req.limit, req.offset, req.start, req.end)
        emails = rows_to_snippets(rows)
        return EmailResponse(
            success=True,
            count=len(emails),
            total_count=total,
            emails=emails,
            message=f"Vector search returned {len(emails)} of {total}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vector search failed: {e}")


# --- Endpoint: hybrid ---------------------------------------------------------
@app.post("/search/hybrid", response_model=EmailResponse)
async def hybrid_search_endpoint(req: HybridSearchRequest):
    """
    FTS top-K + Vector top-K -> fuse with RRF -> optional MMR -> fetch rows in fused order -> paginate.
    """
    try:
        ordered_ids, total = hybrid_retrieve_ids(
            query=req.query,
            start=req.start,
            end=req.end,
            limit=req.limit,
            offset=req.offset,
            fts_k=req.fts_k,
            vec_k=req.vec_k,
            mmr_lambda=req.mmr_lambda,
        )
        rows = fetch_emails_by_ids_preserve(ordered_ids)
        emails = rows_to_snippets(rows)

        return EmailResponse(
            success=True,
            count=len(emails),
            total_count=total,
            emails=emails,
            message=f"Hybrid search returned {len(emails)} (approx total {total}).",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hybrid search failed: {e}")


# --- Endpoint: chat answer (retrieve -> LLM summarize) ------------------------
@app.post("/chat/answer", response_model=ChatAnswer)
async def chat_answer(req: ChatAnswerRequest):
    try:
        # Validate mode here (simpler than pydantic v1/v2 gymnastics)
        if req.mode not in {"vector", "keyword", "hybrid"}:
            raise HTTPException(status_code=400, detail="mode must be one of: vector | keyword | hybrid")

        # 1) Retrieve according to mode
        if req.mode == "vector":
            rows, total = vector_search_sql(req.query, req.limit, req.offset, req.start, req.end)
            ordered_ids = [r[0] for r in rows]
        elif req.mode == "keyword":
            rows, total = search_emails_sql(req.query, req.limit, req.offset, req.start, req.end, req.include_body)
            ordered_ids = [r[0] for r in rows]
        else:  # hybrid
            mmr_lambda = req.mmr_lambda if req.mmr_lambda is not None else 0.3
            ordered_ids, total = hybrid_retrieve_ids(
                query=req.query,
                start=req.start,
                end=req.end,
                limit=req.limit,
                offset=req.offset,
                fts_k=100,
                vec_k=100,
                mmr_lambda=mmr_lambda,
            )
            rows = fetch_emails_by_ids_preserve(ordered_ids)

        emails = rows_to_snippets(rows)

        results = EmailResponse(
            success=True,
            count=len(emails),
            total_count=total,
            emails=emails,
            message=f"Retrieved {len(emails)} of ≈{total} for '{req.query}' via {req.mode}",
        )

        # 2) Summarize with LLM (grounded)
        docs = []
        for r in emails:
            body_preview = _compress(r.body_html or "", settings.max_llm_chars_body_preview)
            docs.append({
                "email_id": r.email_id,
                "from": r.from_name or r.from_address or "Unknown",
                "received": r.received_datetime.isoformat() if r.received_datetime else None,
                "snippet_text": _compress(r.snippet_text or "", settings.max_llm_chars_snippet),
                "body_preview": body_preview,
            })

        system = (
            "You are an email-marketing analyst. Answer using ONLY the provided emails. "
            "Return strict JSON with keys: summary (string), citations (array of email_id integers). "
            "If evidence is weak or mixed, say so briefly."
        )
        user = {
            "query": req.query,
            "instructions": [
                "Be concise: 3–6 sentences. Bullets allowed.",
                "Prioritize concrete offers (percent off, code, holiday cues) and color trends.",
                "Do not include any email_id you did not receive.",
            ],
            "emails": docs,
        }

        data = _openai_chat_json([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ])
        summary = (data.get("summary") or "").strip()
        cits = data.get("citations") or []
        citations = [int(x) for x in cits if isinstance(x, (int, str)) and str(x).isdigit()]

        if not summary:
            summary = f"Found {len(emails)} relevant emails."
            if not citations:
                citations = [e.email_id for e in emails[:5]]

        return ChatAnswer(summary=summary, citations=citations, results=results)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat_answer failed: {e}")


# ==============================================================================
#                           IMAGE SEARCH (APPEND-ONLY)
# ==============================================================================
import base64
import io
import requests
from typing import List, Optional as _Optional
from pydantic import BaseModel as _BaseModel, Field as _Field
from PIL import Image

# If torch/open_clip are optional in your env, keep imports here to avoid import-time failures
try:
    import torch
    import open_clip

    _HAS_CLIP = True
except Exception as _e:
    log.warning("open_clip/torch not available: %s", _e)
    _HAS_CLIP = False


class ImageTextSearchRequest(_BaseModel):
    text: str = _Field(min_length=1, description="e.g., 'warm fall neutrals' or 'bold red banners'")
    start: _Optional[date] = None
    end: _Optional[date] = None
    brand: _Optional[str] = None
    limit: int = _Field(12, ge=1, le=50)
    offset: int = _Field(0, ge=0)


class ImageUrlSearchRequest(_BaseModel):
    image_url: str = _Field(min_length=5, description="Public URL of a reference image or data URL")
    start: _Optional[date] = None
    end: _Optional[date] = None
    brand: _Optional[str] = None
    limit: int = _Field(12, ge=1, le=50)
    offset: int = _Field(0, ge=0)


class ImageHit(_BaseModel):
    email_id: int
    hero_image_url: _Optional[str] = None
    from_name: _Optional[str] = None
    snippet_text: _Optional[str] = None
    received_datetime: _Optional[datetime] = None
    cosine_sim: float


class ImageSearchResponse(_BaseModel):
    success: bool
    count: int
    total_count: int
    items: List[ImageHit]
    message: str


# -------- CLIP model (lazy) ---------------------------------------------------
_CLIP = {"ready": False, "model": None, "prep": None, "device": "cpu", "tokenizer": None}


def _clip_ensure_loaded():
    if not _HAS_CLIP:
        raise RuntimeError("Image search is unavailable: torch/open_clip not installed.")
    if _CLIP["ready"]:
        return
    device = "cuda" if hasattr(torch, "cuda") and torch.cuda.is_available() else "cpu"
    # Use the same model you used for image embeddings during backfill
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai")
    model = model.to(device).eval()
    tokenizer = open_clip.get_tokenizer("ViT-L-14")
    _CLIP.update({"ready": True, "model": model, "prep": preprocess, "device": device, "tokenizer": tokenizer})
    log.info("Loaded CLIP ViT-L-14 on %s", device)


def _l2_norm(t):
    return t / (t.norm(dim=-1, keepdim=True) + 1e-12)


def _vec_to_sql(v) -> str:
    arr = v.squeeze(0).tolist()
    return "[" + ",".join(f"{x:.7f}" for x in arr) + "]"


# -------- Embedding helpers ---------------------------------------------------
def _embed_text_unit_clip(text: str) -> str:
    _clip_ensure_loaded()
    tok = _CLIP["tokenizer"](text)
    if not isinstance(tok, torch.Tensor):
        tok = torch.tensor(tok)
    tokens = tok.to(_CLIP["device"])
    with torch.inference_mode():
        feats = _CLIP["model"].encode_text(tokens)
        feats = _l2_norm(feats).cpu()
    return _vec_to_sql(feats)


def _embed_image_url_unit_clip(url: str) -> str:
    _clip_ensure_loaded()

    # Handle base64 data URLs (data:image/...;base64,...)
    if url.startswith("data:image/"):
        header, data = url.split(",", 1)
        img_data = base64.b64decode(data)
        img = Image.open(io.BytesIO(img_data)).convert("RGB")
    else:
        # Regular URL - fetch via HTTP
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")

    with torch.inference_mode():
        tens = _CLIP["prep"](img).unsqueeze(0).to(_CLIP["device"])
        feats = _CLIP["model"].encode_image(tens)
        feats = _l2_norm(feats).cpu()
    return _vec_to_sql(feats)


# -------- SQL builder ---------------------------------------------------------
def _image_search_sql(where_extra: List[str]) -> str:
    """
    Searches by ANN over img_embedding_unit (unit vectors). Requires:
      - emails.img_embedding_unit vector(...)
      - emails.hero_image_url text
      - HNSW index on img_embedding_unit (vector_cosine_ops)
    """
    where_core = ["e.img_embedding_unit IS NOT NULL"] + where_extra
    where_sql = " AND ".join(where_core)
    return f"""
      WITH q AS (SELECT %s::vector AS v)
      SELECT e.email_id,
             e.hero_image_url,
             e.from_name,
             e.snippet_text,
             e.received_datetime,
             1 - (e.img_embedding_unit <#> q.v) AS cosine_sim,
             COUNT(*) OVER() AS total_count
      FROM emails e, q
      WHERE {where_sql}
      ORDER BY e.img_embedding_unit <-> q.v
      LIMIT %s OFFSET %s
    """


# -------- Meta: quick stats ---------------------------------------------------
@app.get("/stats/image-index")
async def stats_image_index():
    try:
        with db_session() as (_, cur):
            cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE img_embedding_unit IS NOT NULL) AS embedded,
                  COUNT(*) FILTER (WHERE hero_image_url IS NOT NULL AND hero_image_url <> '') AS with_urls,
                  COUNT(*) AS total
                FROM emails
            """
            )
            row = cur.fetchone()
        return {"embedded": row[0], "with_urls": row[1], "total": row[2]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------- Endpoints: text → image --------------------------------------------
@app.post("/search/image-text", response_model=ImageSearchResponse)
async def image_text_search(req: ImageTextSearchRequest):
    try:
        qv = _embed_text_unit_clip(req.text)
        extra: List[str] = []
        args: List[object] = []

        date_clauses, date_args = build_date_filters(req.start, req.end, alias="e.")
        extra.extend(date_clauses)
        args.extend(date_args)

        if req.brand:
            extra.append("(e.from_name ILIKE %s OR e.from_address ILIKE %s)")
            args += [f"%{req.brand}%", f"%{req.brand}%"]

        sql = _image_search_sql(extra)
        with db_session() as (_, cur):
            # Optional: improve recall at query-time
            try:
                cur.execute("SET LOCAL hnsw.ef_search = 80;")
            except Exception:
                pass
            cur.execute(sql, [qv] + args + [req.limit, req.offset])
            rows = cur.fetchall()

        items = [
            ImageHit(
                email_id=r[0],
                hero_image_url=r[1],
                from_name=r[2],
                snippet_text=r[3],
                received_datetime=r[4],
                cosine_sim=float(r[5]),
            )
            for r in rows
        ]
        total = rows[0][-1] if rows else 0

        return ImageSearchResponse(
            success=True,
            count=len(items),
            total_count=total,
            items=items,
            message=f"Found {len(items)} of {total} images for '{req.text}'.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"image-text search failed: {e}")


# -------- Endpoints: image → image -------------------------------------------
@app.post("/search/image-image", response_model=ImageSearchResponse)
async def image_image_search(req: ImageUrlSearchRequest):
    try:
        qv = _embed_image_url_unit_clip(req.image_url)
        extra: List[str] = []
        args: List[object] = []

        date_clauses, date_args = build_date_filters(req.start, req.end, alias="e.")
        extra.extend(date_clauses)
        args.extend(date_args)

        if req.brand:
            extra.append("(e.from_name ILIKE %s OR e.from_address ILIKE %s)")
            args += [f"%{req.brand}%", f"%{req.brand}%"]

        sql = _image_search_sql(extra)
        with db_session() as (_, cur):
            try:
                cur.execute("SET LOCAL hnsw.ef_search = 80;")
            except Exception:
                pass
            cur.execute(sql, [qv] + args + [req.limit, req.offset])
            rows = cur.fetchall()

        items = [
            ImageHit(
                email_id=r[0],
                hero_image_url=r[1],
                from_name=r[2],
                snippet_text=r[3],
                received_datetime=r[4],
                cosine_sim=float(r[5]),
            )
            for r in rows
        ]
        total = rows[0][-1] if rows else 0

        return ImageSearchResponse(
            success=True,
            count=len(items),
            total_count=total,
            items=items,
            message=f"Found {len(items)} similar images.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"image-image search failed: {e}")


# --- Entrypoint ---------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    # Run from the project root:
    #   uvicorn src.app:app --reload
    uvicorn.run("src.app:app", host="0.0.0.0", port=8000, reload=True)
