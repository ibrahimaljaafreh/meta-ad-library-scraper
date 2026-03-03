# Meta Ad Library Scraper

Scrapes results from **Meta Ad Library** with filters: **Country: All**, **Ads: All**, and a configurable search keyword. Results are sorted by **Most recent**. Outputs JSON and CSV with `library_id`, `ad_url`, `started_running`, `sponsor`, `ad_body`, and `media_url`.

---

## Prerequisites

- **Python** 3.8 or newer  
  - [python.org](https://www.python.org/downloads/) (Windows/Linux)
- **pip** (usually included with Python)  
  - Upgrade: `python -m pip install --upgrade pip`
- **Playwright** (installed via `requirements.txt`)  
  - Uses Chromium; the script runs `python -m playwright install chromium` once.

---

## Setup

### Windows (PowerShell)

```powershell
cd path\to\Scraper
pip install -r requirements.txt
python -m playwright install chromium
```

Single line:

```powershell
cd path\to\Scraper; pip install -r requirements.txt; python -m playwright install chromium
```

### Linux / macOS (bash)

```bash
cd /path/to/Scraper
pip install -r requirements.txt
python3 -m playwright install chromium
```

Single line:

```bash
cd /path/to/Scraper && pip install -r requirements.txt && python3 -m playwright install chromium
```

---

## Usage

| Option | Description |
|--------|-------------|
| `--keyword`, `-q` | Search keyword (default: `palpay`) |
| `--limit`, `-n` | Fetch only the last N ads, e.g. `-n 10` or `-n 20` (default: all) |
| `--no-headless` | Show the browser window |
| `--output`, `-o` | Output directory (default: `output`) |
| `--scroll-pause` | Seconds to wait after each scroll (default: 2.5) |
| `--max-scrolls` | Max scroll steps (default: 600) |
| `--no-new-stop` | Stop after this many scrolls with no new IDs (default: 8) |
| `--month`, `-m` | Fetch all ads, then keep only ads whose `started_running` is in this month (e.g. `jan`, `feb`, `oct`) |
| `--country`, `-c` | Country code (e.g. `PS`, `US`, `GB`). Default `ALL`. |

### Examples

**Default (all results, keyword "palpay"):**

```bash
python meta_ad_library_scraper.py
```

**Custom keyword:**

```bash
python meta_ad_library_scraper.py --keyword "bank of palestine"
```

**Last 10 or 20 ads only:**

```bash
python meta_ad_library_scraper.py --limit 10
python meta_ad_library_scraper.py -n 20 --keyword palpay
```

**Visible browser:**

```bash
python meta_ad_library_scraper.py --no-headless
```

**Custom output directory:**

```bash
python meta_ad_library_scraper.py -o my_results
```

**By month (fetch all, then keep only ads started in that month):**

```bash
python meta_ad_library_scraper.py --keyword palpay --month feb
python meta_ad_library_scraper.py -q "bank of palestine" -m jan
```

Use 3-letter month or full name: `jan`, `feb`, `mar`, `apr`, `may`, `jun`, `jul`, `aug`, `sep`, `oct`, `nov`, `dec` (or e.g. `january`, `february`). Output and files contain only ads whose `started_running` matches that month.

**By country (default is ALL):**

```bash
python meta_ad_library_scraper.py --keyword palpay --country PS
python meta_ad_library_scraper.py -q palpay -c US
```

Use 2-letter ISO code: `PS` (Palestine), `US`, `GB`, `JO`, `EG`, etc. Default is `ALL` (all countries).

On Linux/macOS use `python3` if `python` points to Python 2:

```bash
python3 meta_ad_library_scraper.py --keyword palpay -n 20
```

### Full command (all options)

Example using every option in one command. Adjust values as needed.

**Windows (PowerShell):**

```powershell
python meta_ad_library_scraper.py --keyword "bank of palestine" --limit 20 --no-headless --output my_results --scroll-pause 3 --max-scrolls 500 --no-new-stop 10
```

**Linux / macOS:**

```bash
python3 meta_ad_library_scraper.py --keyword "bank of palestine" --limit 20 --no-headless --output my_results --scroll-pause 3 --max-scrolls 500 --no-new-stop 10
```

Short form (same behavior):

```bash
python meta_ad_library_scraper.py -q "bank of palestine" -n 20 --no-headless -o my_results --scroll-pause 3 --max-scrolls 500 --no-new-stop 10
```

| Part | Meaning |
|------|---------|
| `--keyword "bank of palestine"` | Search term |
| `--limit 20` | Only the last 20 ads |
| `--no-headless` | Show browser window |
| `--output my_results` | Save files in `my_results/` |
| `--scroll-pause 3` | Wait 3 seconds after each scroll |
| `--max-scrolls 500` | Stop after 500 scroll steps |
| `--no-new-stop 10` | Stop after 10 scrolls with no new IDs |
| `--month feb` | (optional) Keep only ads with `started_running` in February |

---

## Output

Each run writes **new files** (no overwrite). Filenames include date and time (to the second):

- **JSON:** `output/meta_ads_<keyword>_<YYYY-MM-DD_HH-MM-SS>.json`
- **CSV:** `output/meta_ads_<keyword>_<YYYY-MM-DD_HH-MM-SS>.csv`

Example: `meta_ads_palpay_2026-02-03_14-30-22.json`. Running the same command again later creates a new pair of files.

Columns: `library_id`, `ad_url`, `started_running`, `sponsor`, `ad_body`, `media_url`. Duplicates are removed by exact `library_id`. Do not close the browser window until the script prints "Saved JSON" / "Saved CSV".
