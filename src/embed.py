import os, sys, math, time
from typing import List, Tuple
from contextlib import contextmanager

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Database.dbconnection import DBConnection

MODEL = "text-embedding-3-small"   # 1536-D
BATCH = 50  # Reduced from 256 to avoid token limits
import os
from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@contextmanager
def db_session():
    db = DBConnection()
    try:
        conn, cur = db.connect()
        yield db, conn, cur
    finally:
        db.close()

def unit(v: List[float]) -> List[float]:
    n = math.sqrt(sum(x*x for x in v)) or 1.0
    return [x / n for x in v]

def to_vec(v: List[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"

def fetch_batch(limit=BATCH, test_mode=False) -> List[Tuple[int, str, str]]:
    if test_mode:
        # For testing: get the latest 10 emails regardless of embedding status
        sql = """
          SELECT email_id, COALESCE(header_text,''), COALESCE(snippet_text,'')
          FROM emails
          ORDER BY received_datetime DESC NULLS LAST, email_id DESC
          LIMIT %s
        """
    else:
        # Original: get emails without embeddings
        sql = """
          SELECT email_id, COALESCE(header_text,''), COALESCE(snippet_text,'')
          FROM emails
          WHERE embedding_unit IS NULL
          ORDER BY email_id
          LIMIT %s
        """
    with db_session() as (_, __, cur):
        cur.execute(sql, (limit,))
        return cur.fetchall()

def embed_texts(texts: List[str]) -> List[List[float]]:
    try:
        res = client.embeddings.create(model=MODEL, input=texts)
        return [d.embedding for d in res.data]
    except Exception as e:
        print(f"❌ Error generating embeddings: {e}")
        print(f"Number of texts: {len(texts)}")
        print(f"Total characters: {sum(len(t) for t in texts)}")
        raise

def backfill():
    total = 0
    while True:
        rows = fetch_batch()
        if not rows:
            print("Done. No more rows to embed.")
            break

        ids = [r[0] for r in rows]
        inputs = []
        for _, h, s in rows:
            t = (h.strip() + "\n" + s.strip()).strip() or "(empty)"
            inputs.append(t[:2000])  # More conservative truncation to avoid token limits

        vecs = embed_texts(inputs)
        uvecs = [unit(v) for v in vecs]

        with db_session() as (_, conn, cur):
            for eid, v, uv in zip(ids, vecs, uvecs):
                cur.execute(
                    """
                    UPDATE emails
                    SET embedding = %s::vector, embedding_unit = %s::vector
                    WHERE email_id = %s
                    """,
                    (to_vec(v), to_vec(uv), eid),
                )
            conn.commit()
        total += len(ids)
        print(f"Embedded {total}…"); time.sleep(0.2)

def test_latest_emails(count=10):
    """Test embedding generation for the latest N emails"""
    print(f"Testing embeddings for latest {count} emails...")
    
    rows = fetch_batch(limit=count, test_mode=True)
    if not rows:
        print("No emails found in database.")
        return
    
    print(f"Found {len(rows)} emails to process:")
    for email_id, header, snippet in rows:
        print(f"  Email ID: {email_id}")
        print(f"  Header: {header[:50]}..." if header else "  Header: (empty)")
        print(f"  Snippet: {snippet[:50]}..." if snippet else "  Snippet: (empty)")
        print()
    
    ids = [r[0] for r in rows]
    inputs = []
    for _, h, s in rows:
        t = (h.strip() + "\n" + s.strip()).strip() or "(empty)"
        inputs.append(t[:2000])  # More conservative truncation to avoid token limits
    
    print("Generating embeddings...")
    vecs = embed_texts(inputs)
    uvecs = [unit(v) for v in vecs]
    
    print(f"Generated {len(vecs)} embeddings (dimension: {len(vecs[0]) if vecs else 0})")
    
    # Show first few dimensions of first embedding as example
    if vecs:
        print(f"Sample embedding (first 5 dims): {vecs[0][:5]}")
        print(f"Sample unit vector (first 5 dims): {uvecs[0][:5]}")
    
    # Update database
    with db_session() as (_, conn, cur):
        for eid, v, uv in zip(ids, vecs, uvecs):
            cur.execute(
                """
                UPDATE emails
                SET embedding = %s::vector, embedding_unit = %s::vector
                WHERE email_id = %s
                """,
                (to_vec(v), to_vec(uv), eid),
            )
        conn.commit()
    
    print(f"✅ Successfully updated embeddings for {len(ids)} emails!")

if __name__ == "__main__":
    assert os.getenv("OPENAI_API_KEY"), "Set OPENAI_API_KEY"
    
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Test mode: embed latest 10 emails
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        test_latest_emails(count)
    else:
        # Normal mode: backfill all emails without embeddings
        backfill()
