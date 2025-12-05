# scripts/hero_image_embed.py
import os, io, re, sys, json, math, time, asyncio
from typing import List, Tuple, Optional
from contextlib import contextmanager

# --- Project path so we can import your DBConnection --------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from Database.dbconnection import DBConnection  # your existing helper

# --- Env / model setup --------------------------------------------------------
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Image embedder: OpenCLIP ViT-L/14 (changeable)
MODEL_NAME = "ViT-L-14"
PRETRAINED = "openai"           # alt: "laion2b_s32b_b82k"
IMG_DIM = 768                   # ViT-L/14 output dim
BATCH = 32                      # embed batch size (images)
FETCH_LIMIT = 200               # DB rows per cycle
IMG_TIMEOUT = 6                 # seconds

# Concurrency for Playwright tabs
MAX_TABS = 3

# Optional cache dir for downloaded images
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".hero_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# --- Dependencies for render / embed -----------------------------------------
import requests
from PIL import Image

import torch
import open_clip

from lxml import html as lxml_html
from playwright.async_api import async_playwright, Error as PWError

# ------------------------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------------------------
@contextmanager
def db_session():
    db = DBConnection()
    try:
        conn, cur = db.connect()
        yield db, conn, cur
    finally:
        db.close()

def to_vec(v: List[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"

def l2_unit(x: torch.Tensor) -> torch.Tensor:
    return x / (x.norm(dim=-1, keepdim=True) + 1e-12)

def ensure_hero_image_columns():
    """
    Ensure the required columns for hero image extraction exist in the emails table.
    Creates them if they don't exist.
    """
    with db_session() as (_, conn, cur):
        try:
            # Check if hero_image_url column exists
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='emails' AND column_name='hero_image_url'
            """)
            if not cur.fetchone():
                print("🔧 Creating hero_image_url column...")
                cur.execute("ALTER TABLE emails ADD COLUMN hero_image_url TEXT")
            
            # Check if img_embedding column exists
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='emails' AND column_name='img_embedding'
            """)
            if not cur.fetchone():
                print("🔧 Creating img_embedding column (768-dim vector)...")
                cur.execute("ALTER TABLE emails ADD COLUMN img_embedding vector(768)")
            
            # Check if img_embedding_unit column exists
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='emails' AND column_name='img_embedding_unit'
            """)
            if not cur.fetchone():
                print("🔧 Creating img_embedding_unit column (768-dim vector)...")
                cur.execute("ALTER TABLE emails ADD COLUMN img_embedding_unit vector(768)")
            
            # Create index for similarity search if it doesn't exist
            cur.execute("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename='emails' AND indexname='idx_emails_img_embedding_unit'
            """)
            if not cur.fetchone():
                print("🔧 Creating index for image embedding similarity search...")
                try:
                    cur.execute("""
                        CREATE INDEX idx_emails_img_embedding_unit 
                        ON emails 
                        USING ivfflat (img_embedding_unit vector_cosine_ops)
                        WITH (lists = 100)
                    """)
                except Exception as e:
                    # If ivfflat isn't available or table is empty, try with gin or btree
                    print(f"   Note: Could not create ivfflat index ({e}), continuing anyway...")
                    # Try simple GIN index as fallback
                    try:
                        cur.execute("""
                            CREATE INDEX idx_emails_img_embedding_unit 
                            ON emails 
                            USING gin (img_embedding_unit vector_cosine_ops)
                        """)
                    except:
                        # If even that fails, just continue without index
                        print("   Warning: Could not create index, queries may be slower")
            
            conn.commit()
            print("✅ Database schema is ready for hero image extraction\n")
        except Exception as e:
            print(f"⚠️  Warning: Could not verify/create columns: {e}")
            print("   Continuing anyway... (columns may already exist)\n")
            conn.rollback()

# ------------------------------------------------------------------------------
# Hero image detection
# ------------------------------------------------------------------------------
SEM = asyncio.Semaphore(MAX_TABS)

async def _extract_from_page(page) -> Optional[str]:
    """Heuristic: big, opaque, non-logo image near viewport center above the fold."""
    return await page.evaluate("""() => {
        const isHero = (i) => {
          const r = i.getBoundingClientRect();
          const area = r.width * r.height;
          if (!area) return false;
          if (r.width < 300 || r.height < 300) return false;
          if (getComputedStyle(i).opacity <= 0.5) return false;
          const txt = (i.alt || '') + ' ' + (i.className || '');
          if (/logo|icon|avatar/i.test(txt)) return false;
          return true;
        };
        const imgs = [...document.images].filter(isHero);
        if (!imgs.length) return null;

        // prefer images currently above the fold
        const above = imgs.filter(i => i.getBoundingClientRect().top < innerHeight);
        const cand = (above.length ? above : imgs).sort((a,b) => {
          const ca = a.getBoundingClientRect(); const cb = b.getBoundingClientRect();
          const aC = Math.abs((ca.top + ca.bottom)/2 - innerHeight/2);
          const bC = Math.abs((cb.top + cb.bottom)/2 - innerHeight/2);
          return aC - bC;
        })[0];
        return cand ? (cand.currentSrc || cand.src) : null;
    }""")

async def hero_from_html_playwright(raw_html: str, timeout_ms: int = 12000) -> Optional[str]:
    async with SEM:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent="Mozilla/5.0 (RAG/1.0)")
            try:
                await page.set_content(raw_html, wait_until="networkidle", timeout=timeout_ms)
                url = await _extract_from_page(page)
                return url
            except PWError:
                return None
            finally:
                await browser.close()

def hero_from_html_fallback(raw_html: str) -> Optional[str]:
    """Pure-HTML fallback: pick the largest <img> with decent size and not a logo."""
    try:
        doc = lxml_html.fromstring(raw_html)
        imgs = doc.xpath("//img[@src or @data-src]")
        best = None
        best_score = 0
        for img in imgs:
            src = img.get("src") or img.get("data-src")
            if not src or src.lower().endswith(".svg"):
                continue
            alt = (img.get("alt") or "") + " " + " ".join(img.get("class", "").split())
            if re.search(r"(logo|icon|avatar)", alt, re.I):
                continue
            w = img.get("width"); h = img.get("height")
            try:
                w = int(w) if w else 0
                h = int(h) if h else 0
            except ValueError:
                w = h = 0
            score = (w * h) or 0
            if score > best_score and (w >= 300 or h >= 300):
                best_score = score
                best = src
        return best
    except Exception:
        return None

async def find_hero_url(raw_html: str) -> Optional[str]:
    url = await hero_from_html_playwright(raw_html)
    return url or hero_from_html_fallback(raw_html)

# ------------------------------------------------------------------------------
# Download & embed image
# ------------------------------------------------------------------------------
def cache_path(url: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", url)[:120]
    return os.path.join(CACHE_DIR, f"{key}.bin")

def fetch_image(url: str, timeout: int = IMG_TIMEOUT) -> Image.Image:
    p = cache_path(url)
    if os.path.exists(p):
        with open(p, "rb") as fh:
            data = fh.read()
    else:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.content
        with open(p, "wb") as fh:
            fh.write(data)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return img

class ImageEmbedder:
    def __init__(self, model_name=MODEL_NAME, pretrained=PRETRAINED, device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
        self.model = self.model.to(self.device).eval()

    @torch.inference_mode()
    def encode_images(self, images: List[Image.Image]) -> torch.Tensor:
        # returns (N, D) already L2-normalized
        batch = torch.stack([self.preprocess(im) for im in images]).to(self.device)
        feats = self.model.encode_image(batch)
        return l2_unit(feats).cpu()

# ------------------------------------------------------------------------------
# DB fetch / update
# ------------------------------------------------------------------------------
def fetch_candidates(limit=FETCH_LIMIT) -> List[Tuple[int, Optional[str], Optional[str]]]:
    """
    Get emails that either:
      - have no hero_image_url, or
      - have a hero_image_url but no img_embedding_unit (embed missing).
    Returns: (email_id, body_html, hero_image_url)
    """
    sql = """
      SELECT email_id, body_html, hero_image_url
      FROM emails
      WHERE (hero_image_url IS NULL) OR (hero_image_url IS NOT NULL AND img_embedding_unit IS NULL)
      ORDER BY email_id
      LIMIT %s
    """
    with db_session() as (_, __, cur):
        cur.execute(sql, (limit,))
        return cur.fetchall()

def update_row_with_url_and_vec(email_id: int,
                                url: Optional[str],
                                vec_unit: Optional[List[float]],
                                vec_raw: Optional[List[float]] = None) -> None:
    with db_session() as (_, conn, cur):
        if url and vec_unit is not None:
            cur.execute("""
              UPDATE emails
              SET hero_image_url = %s,
                  img_embedding = %s::vector,
                  img_embedding_unit = %s::vector
              WHERE email_id = %s
            """, (url, to_vec(vec_raw or vec_unit), to_vec(vec_unit), email_id))
        elif url and vec_unit is None:
            cur.execute("""
              UPDATE emails
              SET hero_image_url = %s
              WHERE email_id = %s
            """, (url, email_id))
        conn.commit()

# ------------------------------------------------------------------------------
# Pipeline
# ------------------------------------------------------------------------------
async def process_batch(embedder: ImageEmbedder, rows: List[Tuple[int, Optional[str], Optional[str]]]) -> int:
    """
    For each row:
      1) if no hero URL -> attempt to extract from body_html
      2) if hero URL present -> download, embed, store vectors
    Returns number of rows successfully embedded.
    """
    # Step 1: determine hero URLs for those missing
    url_tasks = []
    need_url: List[Tuple[int, Optional[str], Optional[str]]] = []
    for (email_id, body_html, hero_url) in rows:
        if hero_url:
            continue
        if not body_html:
            continue
        need_url.append((email_id, body_html, hero_url))
        url_tasks.append(find_hero_url(body_html))

    new_urls: List[Optional[str]] = []
    if url_tasks:
        new_urls = await asyncio.gather(*url_tasks, return_exceptions=False)

    url_map: dict[int, str] = {}
    for (row, url) in zip(need_url, new_urls):
        eid = row[0]
        if url:
            url_map[eid] = url
            update_row_with_url_and_vec(eid, url, None, None)  # store URL now

    # Step 2: prepare list of all URLs that need embedding
    to_embed: List[Tuple[int, str]] = []
    for (email_id, _body, hero_url) in rows:
        url = hero_url or url_map.get(email_id)
        if url:
            to_embed.append((email_id, url))

    # Step 3: download & embed in mini-batches
    ok = 0
    i = 0
    while i < len(to_embed):
        batch = to_embed[i:i+BATCH]
        i += BATCH

        imgs: List[Image.Image] = []
        meta: List[Tuple[int, str]] = []
        for eid, url in batch:
            try:
                imgs.append(fetch_image(url, timeout=IMG_TIMEOUT))
                meta.append((eid, url))
            except Exception as e:
                print("skip download", eid, url, e)

        if not imgs:
            continue

        try:
            feats = embedder.encode_images(imgs)     # (N, D) L2-normalized
            for (eid, url), fv in zip(meta, feats):
                vec_unit = fv.tolist()
                update_row_with_url_and_vec(eid, url, vec_unit, vec_unit)  # store unit in both cols (simple)
                ok += 1
        except Exception as e:
            print("embed batch error:", e)

    return ok

async def run(test_mode: bool = False, max_loops: int = 9999):
    # Ensure database schema is ready
    ensure_hero_image_columns()
    
    embedder = ImageEmbedder(MODEL_NAME, PRETRAINED)
    loops = 0
    total_embedded = 0

    while loops < max_loops:
        rows = fetch_candidates(limit=(10 if test_mode else FETCH_LIMIT))
        if not rows:
            print("✅ No more candidates.")
            break

        embedded = await process_batch(embedder, rows)
        total_embedded += embedded
        loops += 1
        print(f"Loop {loops}: embedded {embedded}, total {total_embedded}")

        # in test mode, do only one loop
        if test_mode:
            break

        # brief pause to be gentle with servers
        time.sleep(0.2)

# ------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    """
    Usage:
      python scripts/hero_image_embed.py           # full run
      python scripts/hero_image_embed.py --test    # single small pass
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Process a small set once")
    args = parser.parse_args()

    # Ensure Playwright is ready: `playwright install chromium`
    try:
        asyncio.run(run(test_mode=args.test))
    except KeyboardInterrupt:
        print("\nInterrupted.")
