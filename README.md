# TrackDeals EU — Car Part Deals Archive

A self-running service that finds genuine price drops on car parts sold in the
EU (eBay + Autodoc), cleans and classifies them, then pushes the good ones to
Telegram / X and archives everything in an English-language, searchable website.

The goals in one line:

> **Find real deals on car parts for popular EU cars, brand them by manufacturer,
> post the best ones where buyers already hang out (Telegram channel, X feed,
> the website), and earn affiliate commissions on every click.**

---

## What it aims to achieve

1. **A trustworthy deal feed.** Not "cheapest random item on eBay", but a
   *genuine deal*: a part from a known manufacturer (BOSCH, FEBI, BREMBO, ATE…)
   whose price is meaningfully below either its own list price (RRP) or the
   market average, AND costs enough to be worth someone's time (≥ €12 eBay,
   ≥ €8 Autodoc, ≥ €6 saved).
2. **Broad, evergreen coverage.** Rather than hardcoding a few searches, it
   covers the full cross product of car model × part: 121 part keywords ×
   thousands of model-fit combos from a real car-catalog build, walked in a
   rotating schedule so coverage grows every run and stale data is re-visited.
3. **Revenue through affiliate links.** eBay EPN deep-links (Campaign ID-config)
   make every outbound click trackable per listing; Autodoc support is ready
   behind a configurable click-tracking template for a future partner program.
4. **Distribution where buyers are.** Pending deals are broadcast to a Telegram
   channel with a photo + formatted price card, plus a ready-to-paste X (Twitter)
   post delivered to a private admin chat so the operator can promote without an
   X API fee.
5. **A fast, English, SEO-friendly archive site.** All collected rows are
   searchable (part search, make/model filter), deal pages carry affiliate links,
   OG/Twitter cards, share buttons, sitemap + robots.txt — ready to rank and to
   be promoted on X and Telegram.
6. **Self-service operation.** Windows daemon mode (`--daemon`) runs the whole
   loop forever — hourly eBay sweeps, daily Autodoc catalogue searches, periodic
   Telegram broadcasts — and auto-starts at login.

---

## The pipeline (end to end)

```
 eBay / Autodoc  ──> scrape ──> clean (junk/quality gate) ──> English title
       ──> classify (real deal?) ──> store  ──> sync to hosted Postgres
       ──> broadcast pending deals to Telegram / X copy to admin chat
       ──> website (FastAPI + Jinja2) serves everything to visitors
```

### 1. Scrape

- **eBay** (`ebay_scraper.py`): for each of the 121 part keywords, does a
  best-match search (`limit=40`, `price_min=5`), fetches per-item details, and
  extracts price history, RRP / comparison price, title, image, item ID.
  Keywords are rescanned at most once per interval (hourly by default) via
  `cadence.due_ebay_keywords`.
- **Autodoc** (`autodoc_scraper.py`): built from a `parts_catalog.py` (121 part
  groups) and a real model catalogue (~6,000+ car models from a few popular EU
  makers). It searches part × brand × model combinations, one combo per model,
  through `schedule.py`'s rotating planner (`search_log` tracks what was already
  tried, never-searched combos first, oldest first afterwards).

### 2. Clean & deem junk

`ebay_scraper` applies quality gates before storage:

- `_JUNK_TOKENS` — titles containing ad/prospekt/brochure/sticker/catalog/
  anzeige/tool-kit/montage terms are dropped.
- `_PARTS_FLOOR` (€4) — sub-floor listings are never promoted.
- part gate + brand gate — the title must match an actual part group and either
  start with a known part manufacturer or mention a known car maker
  (`brand_names.py`).

### 3. Translate

`translate_parts.py` turns German titles ("BOSCH Bremsscheibe Vorderachse
260x22mm") into clean English for display and search. `llm_engine.py` uses
Gemini when `GEMINI_API_KEY` is present to also extract the exact compatible
vehicle(s) ("VW Golf 6 1.4 TSI") and a normalised condition; it degrades
gracefully to a rule-based path without a key. `backfill_translate.py` re-applies
the grown translation dictionaries to existing rows.

### 4. Classify — is this a *real* deal?

`deal_filter.is_worth_deal(sale, avg, retail, min_discount=15, min_price, min_saved=6)`
accepts a product only if it has **one** of two proofs of value:

- **Proof A — seller-marked discount**: the listing itself advertises a discount
  off its own RRP (eBay `marketingPrice` / Autodoc list price) with savings
  ≥ €6 and ≥ 15%.
- **Proof B — below market**: the price is ≥ 15% below the current market
  average for that part (peer batch average) with ≥ €6 saved.

Plus hard floors:

| source  | min price | min saved | brand required |
|---------|-----------|-----------|----------------|
| eBay    | €12       | €6        | yes (known part maker) |
| Autodoc | €8        | €6        | no (catalogue brands)   |

A row stores `discount_percentage` and the proof base; rows that fail are
stored as plain catalog/index rows (searchable, never broadcast).
`reclassify_deals.py` re-applies the current rule to every stored row, so old
data is re-aligned whenever the definition changes.

### 5. Store

SQLite locally (`database.py`, SQLAlchemy models: `Deal`, `Brand`,
`VehicleModel`, `SearchLog`, `EbayKeywordLog`, `deal_model_association`…), with
deal statuses that drive everything:

| status    | meaning |
|-----------|---------|
| `pending` | a deal, not yet broadcast — queued for Telegram/X |
| `published`| broadcast to the channel already |
| `search`  | cached result, site-only (from a visitor-triggered live scan) |
| `catalog` | collected row, not a deal — powers search/index |

`crud.py` stores/updates rows, never demotes a deal once promoted (except by an
explicit reclassify). `cadence.purge_stale_ebay` drops stale catalog/search
snapshots after 14 days so the index doesn't rot, while deals are kept forever.

### 6. Monetise

`affiliate.py` wraps every outbound product URL in an affiliate deep link before
it's stored or rendered:

- **eBay EPN**: `epn_epn_link()` appends
  `mkevt=1&mkcid=1&mkrid=711-53200-19255-0&campid=…&customid=<itemId>&toolid=10001`
  once `EPN_CAMPAIGN_ID` is set (customid = item ID, so every click is
  attributable per listing).
- **Autodoc**: `autodoc_affiliate_link()` substitutes the URL into a
  click-tracking template from `AUTODOC_AFFILIATE_URL` (contains `{url}`),
  ready for whenever a partner program is approved.

Without any IDs configured it returns the plain URL — the whole pipeline and
site keep working, just without commission.

### 7. Broadcast

`telegram_distribute.py` sends each pending deal to the Telegram channel
(`TELEGRAM_CHAT_ID`) using a photo + formatted price card
(`format_deal_message`), optionally falls back to text, and marks it
`published`. A private admin chat (`TELEGRAM_ADMIN_CHAT_ID`) additionally gets
the ready-to-post X copy ("…for VW Golf… 💶 22.75 € (avg 24.51 €, -49%)"),
bypassing X's paid API for the operator.

### 8. Serve

`website.py` (FastAPI + Jinja2, templated with `templates/`):

| route | purpose |
|-------|---------|
| `/`          | Hero + stats bar, top 12 eBay deals, "More deals" (Autodoc + prepare eBay) |
| `/deals`     | All deals, filterable (brand, source) |
| `/deal/{id}` | Detail page: images, price card, brand/source badges, meta, affiliate CTA, X/Telegram share buttons |
| `/search`    | Instant indexed search (part + brand + model fit), `?live=1` triggers a real Autodoc scrape for unmatchable parts |
| `/out/{id}`  | Redirect through the stored affiliate link |
| `/about`, `/robots.txt`, `/sitemap.xml` | meta + SEO |
| 404 / 500    | friendly error pages |

Every page carries OG/Twitter meta tags generated from the deal itself.

### 9. Host & sync

- `sync_to_remote.py` mirrors local SQLite → hosted Postgres (Neon), which the
  Render-hosted website reads (Render's free tier has no persistent disk, so
  Postgres is the source of truth for production). It upserts, deletes rows no
  longer present, and keeps brands/models tables in sync.
- `prune_ebay_rows.py` is the one-off/periodic cleanup that re-applies the junk
  token filter and price-floor demotions to already-stored rows.

---

## Running it

```bash
# one-off eBay sweep of due keywords for Autodoc + eBay
python main.py

# Autodoc catalogue sweep (next 8 brand-model-part combos)
python main.py --autodoc

# full catalogue-like eBay sweep (all 121 keywords, limit 40) — heavy
python main.py --ebay-all --limit 40

# headless forever-loop: eBay hourly, Autodoc daily, Telegram broadcasts
python -u main.py --daemon --headless --telegram

# push pending deals to Telegram / admin X copy
python telegram_distribute.py                # real send
python telegram_distribute.py --dry-run      # preview only

# sync local DB to the hosted Postgres (Neon)
python sync_to_remote.py
```

Environment (`.env`, never commit): `EPN_CAMPAIGN_ID`, `AUTODOC_AFFILIATE_URL`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID`,
`DATABASE_URL` (remote Postgres), `GEMINI_API_KEY`, `ALLOW_LIVE_SCRAPE` (default
`"0"`), plus the deal thresholds `EBAY_DEAL_MIN_PRICE`, `AUTODOC_DEAL_MIN_PRICE`,
`DEAL_MIN_SAVED`, `MIN_DISCOUNT`.

On Windows the daemon is launched hidden at login via the Startup-folder VBS
(`daemon_start.cmd` + `daemon_hidden.vbs`, local-only, untracked).

---

## Key design decisions (the "why")

- **Deal quality beat deal quantity.** The first sweeps produced "deals" that
  were literally €1–6 moped bits, screws and brochures, because "cheapest in
  batch" isn't a deal. The brand gate + price/savings floors + RRP proof fixed
  that: a €2 no-name doodad can never be promoted again, a €14 BOSCH part with
  −49% RRP always can.
- **Cheapest-first sorting poisons averages.** eBay was previously swept sorted
  by price (ascending), which dragged every batch average down and promoted the
  cheapest outliers. Best-match ranking + a €5 price band gives a fair market
  average.
- **Never demote automatically, never re-broadcast.** Deals stay published once
  broadcast; status transitions are explicit and auditable via reclassify.
- **Degrade gracefully.** No affiliate ID, no LLM key, no Telegram token — every
  subsystem keeps the core pipeline working. Only the optional revenue/broadcast
  parts light up when configured.

---

## Module map

| file | job |
|------|-----|
| `main.py` | pipeline CLI + daemon, sweep orchestration, `_store` deal logic |
| `ebay_scraper.py` | eBay search/detail, junk filter, quality gate, price band |
| `autodoc_scraper.py` | Autodoc catalogue + product scraping |
| `parts_catalog.py` | 121 part groups (DE/EN) + eBay keywords |
| `brand_names.py` | part-maker + car-maker detection, brand gate |
| `deal_filter.py` | `is_worth_deal` — the deal definition (Proof A/B + floors) |
| `reclassify_deals.py` | re-align all stored rows with the current deal rule |
| `prune_ebay_rows.py` | delete junk rows, ax under-floor rows |
| `schedule.py` | rolling part×brand×model search planner + `search_log` |
| `cadence.py` | which eBay keywords are due, stale-row purge |
| `translate_parts.py` / `llm_engine.py` | DE→EN titles (+ LLM vehicle extraction) |
| `backfill_translate.py` | re-apply translation dictionaries to old rows |
| `crud.py` | storage/query layer, deal listing, site stats |
| `database.py` | SQLite models + session + local engine |
| `affiliate.py` | eBay EPN / Autodoc affiliate link wrapping |
| `deals_format.py` | one message format for pipeline, Telegram, site |
| `telegram_distribute.py` | channel broadcast + admin X copy |
| `website.py` + `templates/` | FastAPI site, SEO, sitemap, deal pages |
| `sync_to_remote.py` | local → hosted Postgres mirror |
| `daemon_start.cmd` / `daemon_hidden.vbs` | Windows autostart wrappers (local) |

For ops notes and SEO/marketing setup see the session history and the local
`*.cmd`/`*.vbs` wrappers.