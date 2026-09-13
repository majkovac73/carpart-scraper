"""
Affiliate link generation for the two money-makers:

  - eBay EPN   (ebay.com / ebay.de ...): classic EPN deep link, needs the
               Campaign ID from your approval email (EPN_CAMPAIGN_ID).
  - Autodoc    (autodoc.de ...): deep-link partner programmes differ per
               network, so we support a configurable click-tracking pattern
               (AUTODOC_AFFILIATE_URL) with "{url}" as the placeholder.

Everything degrades gracefully: while no IDs are configured the plain product
URL is returned, so the pipeline and website keep working day one.
"""

import os
import urllib.parse

# EPN network id (same for all partners of the eBay Partner Network).
EPN_NETWORK_ID = os.getenv("EPN_NETWORK_ID", "711-53200-19255-0")


def ebay_epn_link(raw_url: str, campaign_id: str = None) -> str:
    """Wraps an eBay item URL into an EPN deep link. Returns the raw URL
    unchanged while EPN_CAMPAIGN_ID is not configured."""
    campid = (campaign_id or os.getenv("EPN_CAMPAIGN_ID", "")).strip()
    if not raw_url or not campid:
        return raw_url

    sep = "&" if "?" in raw_url else "?"

    # Use the item id as customid so every click is attributable per listing.
    if "/itm/" in raw_url:
        customid = raw_url.split("/itm/")[-1].split("?")[0].strip("/")
    else:
        customid = "trackdeals"

    return (f"{raw_url}{sep}mkevt=1&mkcid=1&mkrid={urllib.parse.quote(EPN_NETWORK_ID)}"
            f"&campid={campid}&customid={customid}&toolid=10001")


def autodoc_affiliate_link(raw_url: str) -> str:
    """Wraps an Autodoc product URL into your partner-network click URL.
    Set AUTODOC_AFFILIATE_URL to a template containing '{url}' (URL-encoded),
    e.g.  https://click.example.com/click?a=1&url={url}
    Returns the raw URL unchanged while the template is not configured."""
    template = os.getenv("AUTODOC_AFFILIATE_URL", "").strip()
    if not raw_url or not template:
        return raw_url
    return template.replace("{url}", urllib.parse.quote(raw_url, safe=""))


def affiliate_link_for_url(raw_url: str) -> str:
    """Routes a product URL to the right affiliate wrapper by source site.
    Returns None for missing input, otherwise always a usable link."""
    if not raw_url:
        return None
    host = (urllib.parse.urlsplit(raw_url).netloc or "").lower()
    if "ebay" in host:
        return ebay_epn_link(raw_url)
    if "autodoc" in host:
        return autodoc_affiliate_link(raw_url)
    return raw_url