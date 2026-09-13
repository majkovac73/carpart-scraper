# TrackDeals EU – Setup & Manual Steps

Everything in this project can run without any API key. The website and Autodoc
scraping work out of the box. The manual steps below unlock: **Telegram
broadcast**, **eBay deals**, **optional Gemini cleaning**, and **public hosting**.

---

## 0) One-time local setup

```powershell
# in the project folder
pip install -r requirements.txt
playwright install chromium
```

Quick sanity check with example data:

```powershell
python seed_catalog.py    # fills the site with 87 brands / 1800+ car models (idempotent)
python seed_demo.py       # inserts 6 DEMO deals into deals.db
python website.py         # open http://localhost:8000
python telegram_distribute.py --dry-run   # see exactly what would be posted
```

---

## 1) Telegram – the only step needed for broadcasting to your group

1. **Create the bot**: in Telegram, open **@BotFather** → `/newbot` → enter a
   name and a username → it returns an `HTTP API` token like
   `123456:ABC-DEF...`. Copy it.

2. **Create the group/channel**:
   - Group: open **Telegram → New Group**, add your bot as a member.
   - Channel: create a channel and add the bot as **Administrator**
     (needed for posting). Set it **Public** so unknown members can find it.

3. **Get the Chat ID** (the number both the code and you need):
   - Send any message inside your group/channel.
   - Open in a browser (replace TOKEN):
     `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - You will see JSON. For a **channel** the id is `result[].channel_post.chat.id`
     (e.g. `-1001234567890`). For a **group** it is `result[].message.chat.id`.
     It usually starts with `-1` or `-100`.

4. **(Optional) Admin Hub for X copies**: start a chat with your bot directly,
   press `/start`, send one message, then open `getUpdates` again and copy the
   `result[].message.chat.id` from that private chat.

5. **Edit `.env`** (same folder; the file is git-ignored):

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=-1001234567890
   TELEGRAM_ADMIN_CHAT_ID=123456789        # optional; X copy goes here
   ```

6. **Test:**

   ```powershell
   python telegram_distribute.py --dry-run
   python telegram_distribute.py            # posts all pending deals to the channel
   ```

   Deals with status `pending` get posted once, then flip to `published`
   (never double-posted). The Admin Hub receives the X copy **without URL** so
   you can paste it to X manually (no API fee).

---

## 2) eBay deals (optional, needed for eBay data)

1. Go to https://developer.ebay.com, register with a personal EBay account.
2. Under **Keys** create an application → **Production Keys** show a
   **Client ID** (App ID) and **Secret**.
3. (Advanced, only if the rate limit complains) in **Manage your keys** enable
   **User Token** (OAuth). The Basic Client Credentials flow used here needs no
   extra permission.
4. Add to `.env`:

   ```
   EBAY_CLIENT_ID=your_production_client_id
   EBAY_CLIENT_SECRET=your_production_secret
   ```

5. Verify: `python -c "from ebay_scraper import fetch_ebay_deals; print(fetch_ebay_deals('Bremsbeläge', 5))"`

---

## 3) Gemini cleaning (optional, better titles/chassis detection)

In `.env` set:

```
GEMINI_API_KEY=your_google_ai_studio_key   # from aistudio.google.com → Get API key
GEMINI_MODEL=gemini-2.5-flash              # optional; default is gemini-2.5-flash
```

Without it the offline extractor is used (already works).

---

## 4) Run the real pipeline

```powershell
# scrape + save new deals (no browser GUI: see autodoc_scraper.py headless setting)
python main.py --min-discount 15

# scrape + save + instantly broadcast new deals to Telegram
python main.py --min-discount 15 --telegram

# full pipeline in one go (scrape → Telegram), or double-click:
run_pipeline.bat
```

Tunables: `--min-discount X` (default from `MIN_DISCOUNT` env, 15),
`--limit N` (raw deals per search), `--no-autodoc` / `--no-ebay`, `--dry-run`.

> Autodoc: the browser needs ~40-60 s per search; 8 vehicles ≈ 6-8 min each run.

---

## 4b) Affiliate links (eBay EPN / Autodoc)

The pipeline writes an `affiliate_link` for every new deal and the website uses
it (falls back to the plain product URL). Until IDs are configured, links stay
plain so nothing breaks.

**eBay (EPN):** when your approval arrives, put the Campaign ID into `.env`
(`EPN_CAMPAIGN_ID=5338xxxxxxx`). eBay item URLs are then wrapped into official
EPN deep links automatically.

**Autodoc:** fill `AUTODOC_AFFILIATE_URL` with your partner-network click
template containing `{url}`, e.g. `https://click.example.com/click?a=1&url={url}`.

Then backfill links for deals that were saved before you set the IDs:

```powershell
python backfill_affiliate.py
```

Re-run `backfill_affiliate.py` any time you change the IDs. It only writes
links that differ from the plain URL, so it's idempotent.

---

## 5) Website

### Local (recommended to start)

```powershell
python website.py            # http://localhost:8000  (or run_website.bat — LAN visible)
```

Pages:
- `/` – home + search by brand / model / keyword
- `/deals` – full archive
- `/deal/<id>` – detail incl. Telegram-format preview
- JSON API: `/api/deals`, `/api/models`, `/api/health`

Search works on `compatible_models` written by the pipeline, so a visitor can
pick "BMW E46" and see only parts that fit it.

**Live search:** when a search finds nothing cached yet, the site scrapes
Autodoc in real time using the browser (opening a visible Chromium window),
caches the results in deals.db and shows them. Results:

- offers that are **≥ MIN_DISCOUNT (default 15%) below** the batch's average
  price become normal `pending` deals → they also leave for Telegram later;
- everything else is kept as a cached `search` snapshot (visible on the site,
  never broadcast).

Repeat searches for the same car/part hit the cache (~instant). A few notes:

- The scrape takes ~10–60 s; the page just waits.
- English part words are converted to German automatically
  (`to_german_keyword`), e.g. "oil filter" → `ölfilter`.
- Live search never pops a browser window: Autodoc/Cloudflare blocks true
  headless Chromium, so the scraper runs a real renderer placed off-screen.
  To watch it while debugging, set `AUTODOC_WINDOW_VISIBLE=1`.
  Make sure `playwright install chromium` ran.

### Reach it from your phone (same WiFi)

Use `http://<your-PC-IP>:8000` (find IP with `ipconfig`). Windows Firewall:
allow the `Python` app on private networks if prompted.

### Public URL quickly (ngrok)

```powershell
ngrok http 8000
```
You get a `https://xxxx.ngrok.app` link. Good for testing Telegram links / phone.

### Deploy for real (Render, free tier)

1. Push this folder to GitHub.
2. Create a Web Service from the repo.
3. Build command: `pip install -r requirements.txt && playwright install chromium`
4. Start command: `python website.py --host 0.0.0.0 --port $PORT`
5. **Persistent database** — Render's free plan has **no disks**, so data
   resets every deploy if you keep the SQLite file. Use a free hosted Postgres:
   - Create a free **Neon** project (neon.tech → New project → pick a region) and copy the connection string.
   - Add a Render **Environment Variable**:
     `SQLALCHEMY_DATABASE_URL = postgresql+psycopg://USER:PASS@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`
     (note the **`+psycopg`** right after `postgresql` — required by the psycopg driver).
   - Push your local data to it once (idempotent, re-run anytime to publish new deals):
     ```powershell
     $env:SQLALCHEMY_DATABASE_URL = "postgresql+psycopg://USER:PASS@ep-xxx.region.aws.neon.tech/neondb?sslmode=require"
     python sync_to_remote.py
     ```
   - Alternative: run the local pipeline (`main.py`) with the same env var, so new deals are written straight to the hosted DB and appear on the site immediately — no manual sync needed.
6. Create the free instance. Done — the site is public.

> The scraper (`main.py`) stays local or on a small host; the website only
> needs read access to deals.db. Alternatively run both on the same server:
> the start command may run `main.py` via the scheduler inside (see §6).

---

## 6) Automation – scrape every 4 hours (recommended once Telegram is set up)

Windows Task Scheduler:

```powershell
schtasks /Create /SC HOURLY /MO 4 /TN "TrackDeals" ^
  /TR "cmd /c C:\full\path\to\carpart scraper\run_pipeline.bat" /ST 06:00
```

This runs: scrape new deals → broadcast pending deals to Telegram → admin X copy.

To log output: replace `run_pipeline.bat` in the command above with
`cmd /c ""C:\...\run_pipeline.bat" >> C:\...\log.txt"`.

---

## 7) Optional: stop the demo data

`seed_demo.py` added `DEMO-*` deals so you can see the UI immediately. They are
marked pending and will be broadcast once you run `python telegram_distribute.py`.
When you want a clean start:

```powershell
python seed_demo.py --wipe   # deletes all deals (demo AND real)
python seed_catalog.py       # re-run after wipe to restore brand/model dropdowns
# or simply:  del deals.db
```

---

## Checklist before going live

- [ ] `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` → `python telegram_distribute.py` posts correctly
- [ ] First real run: `python main.py --min-discount 15 --telegram`
- [ ] Website works at `http://localhost:8000`
- [ ] (optional) `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET` added, eBay deals appear
- [ ] (optional) `GEMINI_API_KEY` added for smarter titles
- [ ] Scheduler created (§6) so the feed updates itself