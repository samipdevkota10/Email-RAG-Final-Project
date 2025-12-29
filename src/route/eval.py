# src/routes/eval.py
import ast
import json
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Any, Iterable
from datetime import datetime
from decimal import Decimal

# Lazy import to avoid circular dependency
# db_session will be imported from app module when needed
def _extract_subject(raw_headers: Optional[str]) -> Optional[str]:
    """
    Safely parse the header blob that we stored as text and extract the Subject.
    Data was persisted via `str(headers)` (single quotes), so we try literal_eval
    first and fall back to JSON parsing.
    """
    if not raw_headers:
        return None

    candidates: Iterable[Any] = ()

    try:
        parsed = ast.literal_eval(raw_headers)
        candidates = parsed if isinstance(parsed, Iterable) else ()
    except Exception:
        try:
            parsed = json.loads(raw_headers)
            if isinstance(parsed, dict):
                candidates = parsed.get("headers", [])
            else:
                candidates = parsed if isinstance(parsed, Iterable) else ()
        except Exception:
            return None

    for header in candidates:
        if isinstance(header, dict):
            name = header.get("name")
            if isinstance(name, str) and name.lower() == "subject":
                value = header.get("value")
                if isinstance(value, str):
                    return value.strip() or None
    return None

router = APIRouter(prefix="/eval", tags=["Evaluation"])


# ---------- MODELS ----------

class EvalEmail(BaseModel):
    email_id: int
    from_name: Optional[str] = None
    from_address: Optional[str] = None
    header_text: Optional[str] = None
    snippet_text: Optional[str] = None
    received_datetime: Optional[datetime] = None
    body_html: Optional[str] = None


class EvalNextEmailResponse(BaseModel):
    done: bool
    email: Optional[EvalEmail] = None


class EvalLabelRequest(BaseModel):
    email_id: int
    has_offer: bool
    offer_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    discount_unit: Optional[str] = None
    holiday: Optional[str] = None
    notes: Optional[str] = None
    labeled_by: Optional[str] = None


# ---------- ROUTES ----------

@router.get("/next-email", response_model=EvalNextEmailResponse)
async def eval_next_email():
    # Lazy import to avoid circular dependency
    from ..app import db_session
    
    sql = """
        SELECT e.email_id,
               e.from_name,
               e.from_address,
               e.header_text,
               e.snippet_text,
               e.received_datetime,
               e.body_html
        FROM emails e
        JOIN email_eval_sample s USING (email_id)
        LEFT JOIN email_offers_labels l ON l.email_id = e.email_id
        WHERE l.email_id IS NULL
        ORDER BY random()
        LIMIT 1;
    """
    with db_session() as (_, cur):
        cur.execute(sql)
        row = cur.fetchone()

    if not row:
        return EvalNextEmailResponse(done=True, email=None)

    subject = _extract_subject(row[3])

    return EvalNextEmailResponse(
        done=False,
        email=EvalEmail(
            email_id=row[0],
            from_name=row[1],
            from_address=row[2],
            header_text=subject or row[4] or "(no subject)",
            snippet_text=row[4],
            received_datetime=row[5],
            body_html=row[6],
        ),
    )


@router.post("/label")
async def eval_label(payload: EvalLabelRequest):
    sql = """
        INSERT INTO email_offers_labels (
            email_id,
            has_offer,
            offer_type,
            discount_value,
            discount_unit,
            holiday,
            notes,
            labeled_by
        )
        VALUES (
            %(email_id)s,
            %(has_offer)s,
            %(offer_type)s,
            %(discount_value)s,
            %(discount_unit)s,
            %(holiday)s,
            %(notes)s,
            COALESCE(%(labeled_by)s, 'manual')
        )
        ON CONFLICT (email_id)
        DO UPDATE SET
            has_offer      = EXCLUDED.has_offer,
            offer_type     = EXCLUDED.offer_type,
            discount_value = EXCLUDED.discount_value,
            discount_unit  = EXCLUDED.discount_unit,
            holiday        = EXCLUDED.holiday,
            notes          = EXCLUDED.notes,
            labeled_by     = EXCLUDED.labeled_by,
            labeled_at     = now();
    """

    # Lazy import to avoid circular dependency
    from ..app import db_session
    
    params = payload.model_dump()

    with db_session() as (conn, cur):
        cur.execute(sql, params)
        conn.commit()

    return {"success": True, "email_id": payload.email_id}
