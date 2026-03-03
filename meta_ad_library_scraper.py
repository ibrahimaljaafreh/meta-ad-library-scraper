"""
Meta Ad Library Scraper
Country: All | Ads: All | Search: configurable (default: palpay)
Fetches all results with infinite scroll and exports JSON/CSV.
"""

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# Base URL: country=ALL, ad_type=all, active ads, keyword in q=, sort by Most recent (newest first)
BASE_URL = (
    "https://www.facebook.com/ads/library/"
    "?active_status=active"
    "&ad_type=all"
    "&country=ALL"
    "&is_targeted_country=false"
    "&media_type=all"
    "&q={keyword}"
    "&search_type=keyword_unordered"
    "&sort_data[direction]=desc"
    "&sort_data[mode]=recent"
)


def get_current_id_count(page):
    """Return number of unique library IDs currently in the DOM."""
    return page.evaluate(
        """
        () => {
            const ids = new Set();
            document.querySelectorAll('div').forEach(div => {
                const text = div.innerText || '';
                if (text.includes('Library ID')) {
                    const m = text.match(/Library ID:\\s*([\\d]+)/i);
                    if (m) ids.add(m[1]);
                }
            });
            return ids.size;
        }
        """
    )


def scroll_to_load_all(page, target_count=None, max_scrolls=600, scroll_pause=2.5, no_new_ids_stop=8):
    """
    Scroll until we have loaded enough ads. Stops when:
    - We have at least target_count unique library IDs (if target_count from page), or
    - Same number of IDs for no_new_ids_stop consecutive checks (no more loading), or
    - max_scrolls reached.
    """
    last_id_count = 0
    no_new_count = 0

    for i in range(max_scrolls):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(scroll_pause)

        current_count = get_current_id_count(page)
        if current_count > last_id_count:
            last_id_count = current_count
            no_new_count = 0
            if target_count is not None:
                print(f"  Loaded {current_count} / {target_count} IDs...")
            else:
                if i % 10 == 0 or i <= 2:
                    print(f"  Loaded so far: {current_count} ads...")
        else:
            if last_id_count > 0:
                no_new_count += 1
                if no_new_count >= no_new_ids_stop:
                    print(f"  No new IDs for {no_new_ids_stop} checks. Total in DOM: {last_id_count}")
                    break
            elif i >= 20:
                print("  No ad cards loaded yet. Try --no-headless to check for login or slow network.")
                break

        # Reached or passed target from "~X results" on page
        if target_count is not None and last_id_count >= target_count:
            print(f"  Reached target: {last_id_count} IDs (page reported ~{target_count} results).")
            break

    return last_id_count


def parse_results_count(page):
    """Extract approximate results count from page text (e.g. '~1,200 results'). Returns int or None."""
    try:
        text = page.content()
        match = re.search(r"~?([\d,]+)\s*results?", text, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
        match = re.search(r"([\d,]+)\s*results?", text, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    except Exception:
        pass
    return None


def wait_for_results_ready(page, timeout_sec=45):
    """Wait until page shows total count or at least one ad. Returns page_total (int or None)."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        page_total = parse_results_count(page)
        if page_total is not None and page_total > 0:
            return page_total
        n = get_current_id_count(page)
        if n > 0:
            return page_total
        time.sleep(2)
    return parse_results_count(page)


# Base URL for a single ad in the library (id = library_id)
AD_DETAIL_URL_TEMPLATE = "https://www.facebook.com/ads/library/?id={id}"

# Month filter: normalize user input to 3-letter (Meta shows "Jan", "Feb", "Oct 11, 2025", etc.)
MONTH_ALIASES = {
    "jan": "jan", "january": "jan", "1": "jan", "01": "jan",
    "feb": "feb", "february": "feb", "2": "feb", "02": "feb",
    "mar": "mar", "march": "mar", "3": "mar", "03": "mar",
    "apr": "apr", "april": "apr", "4": "apr", "04": "apr",
    "may": "may", "5": "may", "05": "may",
    "jun": "jun", "june": "jun", "6": "jun", "06": "jun",
    "jul": "jul", "july": "jul", "7": "jul", "07": "jul",
    "aug": "aug", "august": "aug", "8": "aug", "08": "aug",
    "sep": "sep", "september": "sep", "9": "sep", "09": "sep",
    "oct": "oct", "october": "oct", "10": "oct",
    "nov": "nov", "november": "nov", "11": "nov",
    "dec": "dec", "december": "dec", "12": "dec",
}


def _normalize_month(user_input):
    if not user_input:
        return None
    key = user_input.strip().lower()
    return MONTH_ALIASES.get(key)


def _ad_matches_month(ad, month_normalized):
    """True if ad's started_running is in the given month (3-letter: jan, feb, ...)."""
    if not month_normalized:
        return True
    raw = (ad.get("started_running") or "").strip()
    if not raw:
        return False
    raw_lower = raw.lower()
    for m in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"):
        if m in raw_lower and m == month_normalized:
            return True
    return False


def extract_ads_from_page(page):
    """
    Extract ad cards in the same order as the GUI: one card per ad, sorted by
    on-page position (top-to-bottom, then left-to-right) to match visual order.
    """
    # Scroll to top so getBoundingClientRect + scrollY gives consistent document positions
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)

    ads = page.evaluate(
        """
        () => {
            const results = [];
            const allDivs = document.querySelectorAll('div');
            const seenIds = new Set();
            const scrollY = window.scrollY || window.pageYOffset;
            const scrollX = window.scrollX || window.pageXOffset;

            for (const div of allDivs) {
                const text = div.innerText || '';
                if (!text.includes('Library ID') || !text.includes('See ad details')) continue;
                const idMatches = text.match(/Library ID\\s*:\\s*[\\d]+/gi);
                if (!idMatches || idMatches.length !== 1) continue;
                let libraryId = '';
                const idMatch = text.match(/Library ID\\s*:\\s*([\\d]+)/i);
                if (idMatch) libraryId = idMatch[1];
                if (libraryId && seenIds.has(libraryId)) continue;
                if (libraryId) seenIds.add(libraryId);

                let adUrl = '';
                const seeDetailsLink = div.querySelector('a[href*="facebook.com/ads/library"]');
                if (seeDetailsLink && seeDetailsLink.href) adUrl = seeDetailsLink.href;
                const anyLink = div.querySelector('a[href*="/ads/library/?id="]');
                if (!adUrl && anyLink && anyLink.href) adUrl = anyLink.href;
                const links = div.querySelectorAll('a[href]');
                for (const a of links) {
                    const h = (a.getAttribute('href') || '').trim();
                    if (h.includes('/ads/library/') && (h.includes('id=') || h.includes('?id='))) {
                        adUrl = h.startsWith('http') ? h : 'https://www.facebook.com' + (h.startsWith('/') ? h : '/' + h);
                        break;
                    }
                }

                let startedRunning = '';
                const dateMatch = text.match(/Started running on\\s*([^\\n]+)/i);
                if (dateMatch) startedRunning = dateMatch[1].trim();

                let sponsor = '';
                const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
                for (let i = 0; i < lines.length; i++) {
                    if (lines[i] === 'Sponsored' && i > 0) {
                        sponsor = lines[i - 1];
                        break;
                    }
                    if (lines[i].includes('Library ID')) break;
                }
                if (!sponsor && lines.length > 0) sponsor = lines[0];

                let adBody = '';
                const seeDetailsIdx = lines.findIndex(l => l.includes('See ad details'));
                if (seeDetailsIdx >= 0) {
                    const before = lines.slice(0, seeDetailsIdx);
                    const drop = new Set(['Active', 'Sponsored']);
                    const bodyLines = before.filter(l =>
                        !l.match(/^Library ID:/i) &&
                        !l.match(/^Started running on/i) &&
                        !drop.has(l) &&
                        l.length > 2
                    );
                    if (bodyLines.length > 0) {
                        const sponsorLine = sponsor ? bodyLines.findIndex(l => l === sponsor) : -1;
                        const start = sponsorLine >= 0 ? sponsorLine + 1 : 0;
                        adBody = bodyLines.slice(start).join(' ');
                    }
                }

                let mediaUrl = '';
                const img = div.querySelector('img');
                if (img && img.src && !img.src.includes('safe_image')) mediaUrl = img.src;

                if (libraryId || sponsor || adBody) {
                    const rect = div.getBoundingClientRect();
                    const docY = rect.top + scrollY;
                    const docX = rect.left + scrollX;
                    const rowTolerance = 50;
                    const rowKey = Math.floor(docY / rowTolerance) * rowTolerance;
                    results.push({
                        library_id: libraryId,
                        ad_url: adUrl || null,
                        started_running: startedRunning,
                        sponsor: sponsor,
                        ad_body: adBody.slice(0, 5000),
                        media_url: mediaUrl || null,
                        _sortY: docY,
                        _sortRow: rowKey,
                        _sortX: docX
                    });
                }
            }
            results.sort((a, b) => (a._sortRow - b._sortRow) || (a._sortX - b._sortX));
            return results.map(({ _sortY, _sortRow, _sortX, ...ad }) => ad);
        }
        """
    )
    # Ensure every ad has ad_url: build from library_id if missing (link to ad page in library)
    for ad in ads:
        if not (ad.get("ad_url") or "").strip():
            lid = ad.get("library_id")
            if lid:
                ad["ad_url"] = AD_DETAIL_URL_TEMPLATE.format(id=lid)
    return ads


def scrape(
    keyword="palpay",
    headless=True,
    output_dir="output",
    timeout_sec=120000,
    scroll_pause=2.5,
    max_scrolls=600,
    no_new_ids_stop=8,
    limit=None,
    month=None,
):
    """
    Open Meta Ad Library with given keyword (country=All, Ads=All), scroll to load
    all results, parse ad cards, and save to JSON and CSV.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(timeout_sec)

        # Encode keyword for URL (e.g. "bank of palestine" -> "bank+of+palestine")
        url = BASE_URL.format(keyword=quote_plus(keyword))
        print(f"Opening: {url}")
        print("Do not close the browser window until the script finishes.")
        # Use "load" not "networkidle" - Facebook never goes idle, so networkidle can hang/close
        page.goto(url, wait_until="load", timeout=60000)
        time.sleep(6)

        try:
            page.wait_for_selector('div[role="main"]', timeout=20000)
        except PlaywrightTimeout:
            pass

        page_total = wait_for_results_ready(page, timeout_sec=45)
        if page_total is not None and page_total > 0:
            print(f"Total ads for keyword '{keyword}': ~{page_total} results.")
        else:
            print(f"Could not read total count for '{keyword}'. Will scroll until no new ads load.")

        target_count = page_total
        if month is not None:
            month_norm = _normalize_month(month)
            if not month_norm:
                print(f"Unknown month '{month}'. Use: jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec (or full name).")
            else:
                print(f"Month filter: will fetch all ~{page_total or '?'} ads, then keep only started_running in {month_norm.upper()}.")
        elif limit is not None:
            target_count = min(page_total, limit) if page_total is not None else limit
            print(f"Limit set: fetching only the last {limit} ads (most recent).")
        if target_count is not None:
            print(f"Scrolling until we load {target_count} IDs...")
        else:
            print("Scrolling until no new ads load...")

        time.sleep(2)
        scroll_to_load_all(
            page,
            target_count=target_count,
            max_scrolls=max_scrolls,
            scroll_pause=scroll_pause,
            no_new_ids_stop=no_new_ids_stop,
        )
        print("Scroll done. Extracting ad cards...")

        ads = extract_ads_from_page(page)
        # Deduplicate only by exact library_id (same id = duplicate)
        by_id = {}
        for i, ad in enumerate(ads):
            lid = (ad.get("library_id") or "").strip()
            key = lid if lid else f"__no_id_{i}"
            if key not in by_id:
                by_id[key] = ad
        ads = list(by_id.values())
        # Keep only first N (newest) when limit is set and month is not
        if month is None and limit is not None and len(ads) > limit:
            ads = ads[:limit]

        # Filter by month when --month is set (started_running must match that month)
        month_norm = _normalize_month(month) if month else None
        if month_norm:
            before = len(ads)
            ads = [a for a in ads if _ad_matches_month(a, month_norm)]
            print(f"Filtered by month {month_norm.upper()}: {len(ads)} ads (from {before} total).")

        unique_count = len(ads)
        if month_norm is None:
            if target_count is not None:
                print(f"Extracted {unique_count} unique ads (page reported ~{target_count} results).")
            else:
                print(f"Extracted {unique_count} unique ads.")

        # Print ad_url + started_running with index to terminal
        if ads:
            print("\n--- Ads (ad_url | started_running) ---")
            for i, ad in enumerate(ads, 1):
                url = (ad.get("ad_url") or "").strip()
                date = (ad.get("started_running") or "").strip()
                print(f"  {i}. {url}  |  {date}")
            print()

        # Safe filename: keyword + timestamp (and month if filtered)
        safe_keyword = re.sub(r"[^\w\-]+", "_", keyword).strip("_") or "search"
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_stem = f"meta_ads_{safe_keyword}_{timestamp}"
        if month_norm:
            file_stem = f"meta_ads_{safe_keyword}_{month_norm}_{timestamp}"
        # JSON
        json_file = output_path / f"{file_stem}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(ads, f, ensure_ascii=False, indent=2)
        print(f"Saved JSON: {json_file}")

        # CSV
        csv_file = output_path / f"{file_stem}.csv"
        if ads:
            import csv
            keys = ["library_id", "ad_url", "started_running", "sponsor", "ad_body", "media_url"]
            with open(csv_file, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                w.writerows(ads)
            print(f"Saved CSV: {csv_file}")

        browser.close()

    return ads


def _is_target_closed_error(e):
    return "TargetClosedError" in type(e).__name__ or (
        "closed" in str(e).lower() and ("target" in str(e).lower() or "browser" in str(e).lower())
    )


def main():
    parser = argparse.ArgumentParser(description="Meta Ad Library Scraper (Country: All, Ads: All)")
    parser.add_argument("--keyword", "-q", default="palpay", help="Search keyword (default: palpay)")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--output", "-o", default="output", help="Output directory (default: output)")
    parser.add_argument("--scroll-pause", type=float, default=2.5, help="Seconds to wait after each scroll (default: 2.5)")
    parser.add_argument("--max-scrolls", type=int, default=600, help="Max scroll steps before stopping (default: 600)")
    parser.add_argument("--no-new-stop", type=int, default=8, help="Stop after this many scrolls with no new IDs (default: 8)")
    parser.add_argument("--limit", "-n", type=int, default=None, metavar="N", help="Fetch only the last N ads (e.g. 10 or 20); default = all")
    parser.add_argument("--month", "-m", type=str, default=None, metavar="MONTH", help="Fetch all ads then keep only started_running in this month (e.g. jan, feb, oct)")
    args = parser.parse_args()

    try:
        scrape(
            keyword=args.keyword,
            headless=not args.no_headless,
            output_dir=args.output,
            scroll_pause=args.scroll_pause,
            max_scrolls=args.max_scrolls,
            no_new_ids_stop=args.no_new_stop,
            limit=args.limit,
            month=args.month,
        )
    except Exception as e:
        if _is_target_closed_error(e):
            print("\n[خطأ] تم إغلاق المتصفح أو الصفحة قبل انتهاء السكريبت.")
            print("لا تُغلق نافذة المتصفح أثناء التشغيل — اتركها مفتوحة حتى يطبع 'Saved JSON/CSV'.")
        raise


if __name__ == "__main__":
    main()
