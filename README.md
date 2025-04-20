# ChartLocker DL

ChartLocker DL is a command-line utility to download MBTiles files from The Chart Locker website (https://chartlocker.brucebalan.com/). It supports both anonymous downloads and premium downloads using MediaFire accounts (via cookies or API).

## Features
- Scrape regions and file listings from The Chart Locker site.
- Interactive selection of region and files to download.
- Anonymous HTML scraping method for public files.
- Premium support via MediaFire API (App ID 42511) or cookies.txt.
- Automatic extraction of ZIP archives after download.

## Requirements
This script is written in Python 3.6+ and depends on the following packages:

```
requests
beautifulsoup4
tqdm
tabulate
fuzzywuzzy
rich
```

Optional packages for enhanced functionality:
```
python-Levenshtein    # faster fuzzy matching
mediafire             # MediaFire API support for premium downloads
```

## Installation
It is strongly recommended to use a Python virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage
```bash
python chartlocker-dl.py [--cookies COOKIES_FILE] [--email EMAIL [--password PASSWORD]] [--charts-dir OUTPUT_DIR]
```

- `--cookies`: path to cookies.txt exported from your browser for MediaFire sessions.
- `--email`, `--password`: MediaFire account credentials for premium API access.
- `--charts-dir`: destination directory for downloaded charts (default: current directory).

The script will prompt you to select a region and then the files to download.

## Notes
- The cookie-based download method has not been thoroughly tested and may be unstable.
- The script is not affiliated with or endorsed by The Chart Locker project or MediaFire.

## Credit
This utility accesses content hosted on The Chart Locker by Bruce Balan. All rights to the original data belong to the Chart Locker website owner.

## Acknowledgements
This script was produced with the help of OpenAI Codex models (o3 and o4-mini).