Project Blueprint: Automotive Arbitrage Feed (EU-TrackDeals)
Date: September 2026
Tech Stack: Python, FastAPI, Playwright, SQLite/PostgreSQL, Next.js
Monetization: eBay Partner Network (EPN), Awin Affiliate Network

Architecture Overview
A 100% headless, server-side data pipeline that scrapes high-value European automotive part discounts, mathematically validates the deal, generates a monetized affiliate URL, and formats the output for manual distribution on X and automated distribution on Telegram.

🗄️ Phase 1: Environment & Database
The foundation. Setting up the environment and creating the ledger so the system never double-posts a deal.

Step 1.1: Initialize the Python environment and install core dependencies (fastapi, sqlalchemy, playwright, python-telegram-bot, google-genai).

Step 1.2: Design the Database Schema (SQLite for local dev). Fields required: id (primary key), product_id (unique), title, retail_price, sale_price, discount_percentage, image_url, affiliate_link, status (pending/published).

Step 1.3: Build basic SQLAlchemy CRUD functions (Create, Read, Update) so the scraper can easily check if a product_id already exists before processing it.

🕷️ Phase 2: Data Ingestion (The Scrapers)
Pulling raw data from European vendors.

Step 2.1: Get eBay Developer API credentials. Build the fetch_ebay_deals() function using the eBay Browse API to query EU "Buy It Now" parts under specific categories.

Step 2.2: Write the Playwright scraper script fetch_autodoc_clearance(). Configure headless browser navigation to bypass basic blocks and extract fully rendered HTML text blocks of discounted items.

🧠 Phase 3: The Logic & LLM Engine
Structuring the messy data and doing the math.

Step 3.1: Write the Gemini API prompt. Pass the raw Playwright text to the LLM to return strict JSON containing: clean_title, chassis_code, and condition.

Step 3.2: Write the Deal Filter. Implement Python logic to calculate the discount percentage: ((retail_price - sale_price) / retail_price) * 100. Reject anything under 25%.

🔗 Phase 4: Link Generation (Monetization)
Converting raw product URLs into tracking links.

Step 4.1: Build generate_epn_link(raw_url). Structure the URL string using your EPN Campaign ID (campid) and Network ID to create the official eBay affiliate redirect.

Step 4.2: Build generate_awin_link(raw_url). Integrate the Awin Link Builder API (using OAuth2/Bearer token from the Awin UI) to programmatically generate deep links for Autodoc/retailers.

📢 Phase 5: Distribution & Next.js Archive
Formatting the data for the Telegram audience, X, and the SEO website.

Step 5.1: Set up the Telegram Bot API. Write the broadcast function to send the image, price format, and direct affiliate link to the public channel.

Step 5.2: Write the "Admin Hub" function. Have the bot send the exact X (Twitter) copy to a private chat for you to manually copy/paste, omitting the URL to bypass the $0.20 X API fee.

Step 5.3: Build the Next.js static archive template and deploy to Vercel. Set up a webhook endpoint.

Step 5.4: Connect FastAPI to Vercel. When a deal is added to the database, trigger the webhook so the Next.js site automatically rebuilds with the new deal.

🚀 Phase 6: Automation & Launch
Moving from local development to the cloud.

Step 6.1: Containerize or push the repository to Railway. Provision a PostgreSQL database and migrate the SQLite data.

Step 6.2: Set up a scheduler (e.g., APScheduler) within FastAPI to run the scraping sequence every 4 hours.

Step 6.3: The Dry Run. Let the system run for 7 days without affiliate IDs to populate the Next.js site and Telegram channel with organic posts.

Step 6.4: Submit the populated Next.js site to EPN and Awin for approval. Once approved, inject API keys and monetize the pipeline.