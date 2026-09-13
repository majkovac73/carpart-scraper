"""
Fills in affiliate links for existing deals (and updates any that changed).

The pipeline writes affiliate links for NEW deals automatically, but anything
already in deals.db keeps only its plain source_url. Run this whenever you add
or change EPN / Autodoc IDs:

    python backfill_affiliate.py

It only stores a link that actually differs from the plain URL (i.e. a real
monetised link), so it's safe to re-run any time.
"""

from dotenv import load_dotenv

from database import SessionLocal, Deal
from affiliate import affiliate_link_for_url

load_dotenv()


def main():
    db = SessionLocal()
    try:
        rows = db.query(Deal).filter(Deal.source_url.isnot(None)).all()
        updated = 0
        for row in rows:
            link = affiliate_link_for_url(row.source_url)
            if not link:
                continue
            if link != row.source_url and row.affiliate_link != link:
                row.affiliate_link = link
                updated += 1
        db.commit()
        print(f"affiliate links: {updated} updated")
        print("Deals without an affiliate link yet (IDs not configured):",
              db.query(Deal).filter(
                  Deal.affiliate_link.is_(None), Deal.source_url.isnot(None)).count())
    finally:
        db.close()


if __name__ == "__main__":
    main()