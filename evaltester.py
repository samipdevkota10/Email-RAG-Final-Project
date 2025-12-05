import psycopg2
import pandas as pd

conn = psycopg2.connect("postgresql://postgres:Balle10#@localhost:5432/EmailDB-local")  # your DB URL

sql = """
SELECT
  e.email_id,
  e.snippet_text,
  e.body_html,
  l.has_offer
FROM email_offers_labels l
JOIN emails e USING (email_id)
JOIN email_eval_sample s USING (email_id);
"""

df = pd.read_sql(sql, conn)

def keyword_rule(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    tokens = [
        " off", "% off", "sale", "save ", "bogo",
        "free shipping", "deal", "clearance", "promo code"
    ]
    return any(tok in t for tok in tokens)

df["baseline_has_offer"] = df["snippet_text"].fillna("").str.lower() + " " + df["body_html"].fillna("")
df["baseline_has_offer"] = df["baseline_has_offer"].apply(keyword_rule)

tp = ((df.baseline_has_offer == True) & (df.has_offer == True)).sum()
fp = ((df.baseline_has_offer == True) & (df.has_offer == False)).sum()
fn = ((df.baseline_has_offer == False) & (df.has_offer == True)).sum()
tn = ((df.baseline_has_offer == False) & (df.has_offer == False)).sum()

precision = tp / (tp + fp) if (tp + fp) else 0
recall    = tp / (tp + fn) if (tp + fn) else 0

print("TP:", tp, "FP:", fp, "FN:", fn, "TN:", tn)
print("Precision:", precision, "Recall:", recall)
