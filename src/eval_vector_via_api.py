import os
import requests
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime

# ------------------------------
# CONFIG
# ------------------------------
API_BASE = os.getenv("MAIL_LENS_API_BASE", "http://localhost:8000")
DATABASE_URL = os.getenv("DATABASE_URL")  # set this in your env
RUN_NAME = "vec_baseline_v1"              # change per experiment
TOP_K = 30                                # how many results per query

# These are the queries you would actually type into the UI in vector mode
EVAL_QUERIES = [
    "emails with discounts",
    "BOGO deals",
    "free shipping offers",
    "clearance sale",
    "holiday promotions",
    "black friday sale",
    "cyber monday deals",
    "new customer offer",
    "loyalty rewards email",
    "weekly promo"
]


def main():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env var is not set")

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    print(f"Using API base: {API_BASE}")
    print(f"Run name: {RUN_NAME}")
    print(f"Queries: {len(EVAL_QUERIES)}")

    all_rows = []

    for q in EVAL_QUERIES:
        print(f"\nQuery: {q!r}")
        url = f"{API_BASE}/search/vector"
        payload = {
            "query": q,
            "limit": TOP_K,
            "offset": 0,
            "start": None,
            "end": None,
        }

        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # Expected shape from your FastAPI /search/vector:
        # {
        #   "success": true,
        #   "count": 30,
        #   "total_count": 1234,
        #   "emails": [...],
        #   "message": "Vector search returned ..."
        # }
        emails = data.get("emails", [])
        print(f"  Retrieved {len(emails)} items")

        for rank, e in enumerate(emails, start=1):
            email_id = e["email_id"]
            all_rows.append((RUN_NAME, q, email_id, rank))

    # Insert into eval_vector_results
    if all_rows:
        print(f"\nInserting {len(all_rows)} rows into eval_vector_results...")
        execute_values(
            cur,
            """
            INSERT INTO eval_vector_results (run_name, query_text, email_id, rank)
            VALUES %s
            """,
            all_rows,
        )
        conn.commit()
        print("Done.")
    else:
        print("No rows to insert.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
