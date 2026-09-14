"""Refreshes the English display titles (title_en) of every stored deal.

Used after the translation dictionaries grow, so old German titles in the DB
get the improved English versions too:

    python backfill_translate.py

It is idempotent and quick (pure dictionary lookup, no network calls).
"""

from dotenv import load_dotenv

from database import SessionLocal, Deal
from translate_parts import to_english_title

load_dotenv()


def main():
    db = SessionLocal()
    try:
        rows = db.query(Deal).all()
        updated = skip = 0
        for row in rows:
            new_en = to_english_title(row.title)
            if new_en != row.title_en:
                row.title_en = new_en
                updated += 1
            else:
                skip += 1
        db.commit()
        print(f"title_en refreshed: {updated} updated, {skip} unchanged "
              f"({len(rows)} total deals)")
    finally:
        db.close()


if __name__ == "__main__":
    main()