# ChartButler

ChartButler is a command-line utility to download MBTiles files from multiple sources for use with OpenCPN, including:
- The Chart Locker (https://chartlocker.brucebalan.com/) by Bruce Balan
- Sailing Grace Charts (https://sailingamazinggrace.com/charts) by S/Y Grace

It supports anonymous HTTP/HTML scraping for downloads from ChartLocker and Sailing Grace sources.

## Features
 - Scrape regions and file listings from The Chart Locker or Sailing Grace sites.
 - Interactive selection of region and files to download.
 - Anonymous HTML scraping method for public files.
 - Automatic extraction of ZIP archives after download.
 - Folder organization based on source, region, and subregion to assist with granular OpenCPN importing.

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
zipfile-deflate64     # deflate64 ZIP extraction support
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
python chartbutler.py --source {chartlocker,savinggrace} [--charts-dir OUTPUT_DIR]
```

- `--source`: choose which site to download from: `chartlocker` or `savinggrace`.
- `--charts-dir`: destination directory for downloaded charts (default: current directory).

The script will prompt you to select a region and then the files to download.

## Examples

A typical workflow keeps the script in one directory and downloads charts into a separate folder. For example:

![Virtualenv setup](screenshots/setup.png)

![CLI invocation](screenshots/cli_a.png)

![Downloading charts into the `charts` directory](screenshots/cli_b.png)

## Notes
 - The script is not affiliated with or endorsed by The Chart Locker project, Sailing Grace, or MediaFire.

## Credit
This utility accesses content hosted on:
- The Chart Locker by Bruce Balan
- Sailing Grace Charts by S/Y Grace

All rights to the original data belong to the respective site owners.

## Acknowledgements
This script was produced with the help of OpenAI Codex models (o3 and o4-mini).