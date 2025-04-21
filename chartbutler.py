#!/usr/bin/env python3
# chartbutler.py · v0.9.1  (April 2025)
#
#  v0.9 + full‑length Area & Notes columns
# ----------------------------------------------------------
#  pip install requests beautifulsoup4 tqdm tabulate fuzzywuzzy
#  (opt) pip install python-Levenshtein  mediafire
# ----------------------------------------------------------

import argparse, os, re, sys, zipfile, shutil
from urllib.parse import urlparse
import requests, bs4, tqdm
from tabulate import tabulate
from fuzzywuzzy import process as fuzz
from rich.console import Console
from rich.table import Table

BASE = "https://chartlocker.brucebalan.com/"
UA   = "ChartButler/0.9.1 (+https://github.com/wrxco/chartbutler)"

# ─────────── CLI ───────────
def cli():
    p = argparse.ArgumentParser(
        description="Download files from The Chart Locker or Sailing Grace"
    )
    p.add_argument("--cookies", help="Path to cookies.txt for MediaFire session")
    p.add_argument("--email", help="MediaFire account email (optional)")
    p.add_argument("--password", help="MediaFire account password (optional)")
    p.add_argument(
        "--charts-dir",
        default=os.getcwd(),
        help="Destination directory for downloaded charts (default: current working directory)"
    )
    p.add_argument(
        "--source",
        choices=["chartlocker", "savinggrace"],
        default=None,
        help="Source site: chartlocker or savinggrace (if omitted, will prompt)"
    )
    return p.parse_args()
    
def pick_source():
    """
    Prompt user to select a source if not provided via CLI.
    """
    sources = ["chartlocker", "savinggrace"]
    print("\nAVAILABLE SOURCES")
    for i, src in enumerate(sources, 1):
        print(f"  {i}. {src}")
    while True:
        ans = input("Select source # or name > ").strip()
        if ans.isdigit() and 1 <= int(ans) <= len(sources):
            return sources[int(ans) - 1]
        if ans in sources:
            return ans
        print(f"Invalid selection '{ans}'. Please choose a valid source.")

# ───── session ─────
def make_session(a):
    # For savinggrace source, skip MediaFire auth entirely
    if getattr(a, 'source', None) == 'savinggrace':
        s = requests.Session()
        s.headers["User-Agent"] = UA
        s.auth_mode = 'anonymous'
        return s
    import getpass
    # start session, set User-Agent, and mount retry adapter for transient errors (e.g., rate limiting)
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    s.headers["User-Agent"] = UA
    # Retry on 429, 500-504 errors, with backoff
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=1,
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    # authentication mode: anonymous | premium | cookies
    mode = 'anonymous'
    # 1) attempt MediaFire API login when email given (premium mode)
    if a.email:
        # prompt for password if missing
        if not a.password:
            try:
                a.password = getpass.getpass(f"MediaFire password for {a.email}: ")
            except (KeyboardInterrupt, EOFError):
                print("\n⚠ No password entered; skipping MediaFire login")
        # if password is now set, try to fetch session token
        if a.password:
            try:
                from mediafire import MediaFireApi
                api = MediaFireApi()
                tok = api.user_get_session_token(
                    app_id="42511",
                    email=a.email,
                    password=a.password
                )
                api._session = tok
                s.headers["Authorization"] = "Bearer " + tok.get("session_token", "")
                s.mediafire_api = api
                mode = 'premium'
            except Exception as e:
                print("⚠ MediaFire login failed:", e)
        else:
            print("⚠ MediaFire login skipped: no password provided")
    # 2) load cookies if file provided and no premium login
    elif a.cookies and os.path.isfile(a.cookies):
        for ln in open(a.cookies, encoding="utf-8"):
            if ln.startswith("#") or not ln.strip():
                continue
            dom, _, path, sec, _, name, val = ln.strip().split("\t")
            s.cookies.set(name, val, domain=dom, path=path, secure=(sec.lower() == "true"))
        mode = 'cookies'
    # 3) warn if password provided without email/cookies
    elif a.password:
        print("⚠ Password provided without email; skipping MediaFire login")
    # report session type
    if mode == 'premium':
        print("✅ Using MediaFire API (premium) session")
    elif mode == 'cookies':
        print("✅ Using cookies-based MediaFire session")
    else:
        print("⚠ No MediaFire credentials; proceeding anonymously")
    # store auth mode
    s.auth_mode = mode
    return s

# ───── helpers ─────
def soup(url,s): r=s.get(url,timeout=60); r.raise_for_status(); return bs4.BeautifulSoup(r.text,"html.parser")
def slugify(t):  return re.sub(r'[^\w\- ]','_',t).strip()
def td_notes(tds):
    for txt in reversed(tds):
        if txt and not re.match(r'^\d+(\.\d+)?\s*(MB|GB)$',txt,flags=re.I):
            return txt
    return ""
def human_size(tok): return tok if re.search(r'\d',tok) else ""
def landing_filename(url):
    """
    Return a suitable filename for the download URL.
    If the URL path ends with a file (has an extension), use that basename,
    otherwise fall back to the prior path segment.
    """
    path = urlparse(url).path.rstrip('/')
    parts = path.split('/')
    if parts:
        last = parts[-1]
        # if last part looks like a file name (contains a dot), use it
        if '.' in last:
            return last
        # otherwise, fallback to previous segment
        if len(parts) >= 2:
            return parts[-2]
        return last or 'file'
    return 'file'

# ───── scrape page ─────
def scrape(sess):
    doc=soup(BASE,sess)
    tree={}; region=None; buf=[]
    skip={"the chart locker","other resources","how to use these files"}
    for tag in doc.find_all(["h2","table"]):
        if tag.name=="h2" and tag.get_text(strip=True):
            if region and buf: tree[region]=parse_region(buf)
            region=tag.get_text(strip=True); buf=[]
        elif tag.name=="table" and region: buf.append(tag)
    if region and buf: tree[region]=parse_region(buf)
    return {r:rows for r,rows in tree.items() if rows and r.lower() not in skip}

def scrape_savinggrace(sess):
    """
    Scrape charts from https://sailingamazinggrace.com/charts.
    Returns dict mapping region labels to list of (area, url, size, note).
    """
    SAVE_URL = "https://sailingamazinggrace.com/charts"
    doc = soup(SAVE_URL, sess)
    regions = {}
    hrs = doc.find_all("hr", id=True)
    for idx, hr in enumerate(hrs):
        # top‑level region
        h2 = hr.find_next("h2")
        if not h2:
            continue
        region_label = h2.get_text(strip=True)
        # limit to this region
        next_hr = hrs[idx+1] if idx+1 < len(hrs) else None
        rows = []
        elem = hr
        current_sub = None
        current_zoom = ""
        # walk through elements until next region
        while True:
            elem = elem.find_next()
            if elem is None or elem == next_hr:
                break
            # detect subregion headings
            if getattr(elem, 'name', None) == 'h3':
                text = elem.get_text(strip=True)
                # extract zoom in parentheses
                m = re.match(r"(.+?)\s*\((.+?)\)", text)
                if m:
                    current_sub = m.group(1).strip()
                    current_zoom = m.group(2).strip()
                else:
                    current_sub = text
                    current_zoom = ""
                continue
            # chart rows
            if getattr(elem, 'name', None) == 'li' and 'row' in elem.get('class', []):
                # area name
                area_div = elem.find('div', class_='area')
                area_txt = area_div.get_text(strip=True) if area_div else ''
                # creation date
                created_div = elem.find('div', class_='created')
                created = created_div.get_text(strip=True) if created_div else ''
                # assemble note with zoom
                if current_zoom:
                    note = f"{created} ({current_zoom})" if created else f"{current_zoom}"
                else:
                    note = created
                # full area path: subregion / area
                if current_sub:
                    area_full = f"{current_sub} / {area_txt}"
                else:
                    area_full = area_txt
                # each map column
                for j, mp in enumerate(elem.find_all('div', class_='map')):
                    a = mp.find('a', href=True)
                    if not a:
                        continue
                    url = a['href']
                    size = a.get_text(strip=True)
                    rows.append((area_full, url, size, note if j == 0 else ''))
        if rows:
            regions[region_label] = rows
    return regions

def parse_region(tables):
    # Parse each <tr> as a group, collecting link counts, group notes, links, and sizes
    all_counts = []    # number of links in each table row
    all_notes = []     # note string for each table row
    all_links = []     # flat list of (area_text, url)
    all_sizes = []     # flat list of "NNN MB/GB" tokens in order

    for tbl in tables:
        # Extract header row to determine which column is area/region/country
        header = []
        thead = tbl.find("thead")
        hdr_tr = thead.find("tr") if thead and thead.find("tr") else next((r for r in tbl.find_all("tr") if r.find("th")), None)
        if hdr_tr:
            header = [th.get_text(strip=True).lower() for th in hdr_tr.find_all(["th", "td"])]
        # Determine which column holds the display name: prefer 'Area', then 'Region', then 'Country'
        area_idx = None
        # substring matching on header labels
        if any("area" in h for h in header):
            area_idx = next(i for i, h in enumerate(header) if "area" in h)
        elif any("region" in h for h in header):
            area_idx = next(i for i, h in enumerate(header) if "region" in h)
        elif any("country" in h for h in header):
            area_idx = next(i for i, h in enumerate(header) if "country" in h)

        # Walk through each data row (one <tr> per group)
        for tr in tbl.find_all("tr"):
            if tr.find("th"): continue
            links = tr.find_all("a", href=lambda u: u and "mediafire.com" in u)
            if not links: continue
            tds = tr.find_all("td")
            # collect sizes
            for td in tds:
                text = td.get_text(" ", strip=True)
                for m in re.findall(r"\d+(?:\.\d+)?\s*(?:MB|GB)", text):
                    all_sizes.append(m)
            # extract group note
            texts = [td.get_text(" ", strip=True) for td in tds]
            note = td_notes(texts)
            all_counts.append(len(links))
            all_notes.append(note)
            # extract area_text and url for each link
            for a in links:
                parent_td = a.find_parent("td")
                try:
                    td_idx = tds.index(parent_td)
                except ValueError:
                    td_idx = None
                if area_idx is not None and td_idx == area_idx:
                    area_txt = a.get_text(strip=True)
                elif area_idx is not None and area_idx < len(tds):
                    area_txt = tds[area_idx].get_text(" ", strip=True)
                else:
                    area_txt = a.get_text(strip=True)
                all_links.append((area_txt, a["href"]))

    # flatten: one row per link; only first link of each group shows the note
    rows = []
    link_idx = 0
    for grp_idx, count in enumerate(all_counts):
        note = all_notes[grp_idx]
        for j in range(count):
            area, url = all_links[link_idx]
            size = all_sizes[link_idx] if link_idx < len(all_sizes) else ""
            rows.append((area, url, size, note if j == 0 else ""))
            link_idx += 1
    return rows

def mediafire_direct(url, s):
    # use the original URL for HTML fallbacks (preserve '/file_premium/' path)
    page_url = url
    # Extract quick key from URL path
    parts = urlparse(page_url).path.rstrip('/').split('/')
    quick_key = parts[-3] if len(parts) >= 3 else None
    api = getattr(s, 'mediafire_api', None)
    # 1) Try API direct link if available
    if api and quick_key:
        try:
            # Attempt to use MediaFire API for a permissioned link
            resp = api.file_get_links(quick_key)
            # resp is the parsed 'response' dict from the API
            # Extract the 'links' wrapper
            wrapper = resp.get('links')
            if wrapper:
                # In some responses, links may be nested under 'link'
                entries = None
                if isinstance(wrapper, dict) and 'link' in wrapper:
                    entries = wrapper['link']
                else:
                    entries = wrapper
                # Normalize to list
                if isinstance(entries, dict):
                    entries = [entries]
                if isinstance(entries, list) and entries:
                    first = entries[0]
                    for key in ('direct_download', 'download_url'):
                        val = first.get(key)
                        if val:
                            print(f"⇱ [MediaFire API] using direct link: {val}")
                            return val
            # no usable links found
            print(f"⚠ [MediaFire API] no download links in response, keys: {list(resp.keys())}")
        except Exception as e:
            print(f"⚠ [MediaFire API] error fetching links for key {quick_key}: {e}")
    # 2) HTML regex fallback (unauthenticated or API fallback)
    try:
        page = s.get(page_url, timeout=60).text
        m = re.search(r'href=["\'](https://download[^"\']+)["\']', page)
        if m:
            fallback = m.group(1)
            print(f"⇱ [HTML regex] fallback link: {fallback}")
            return fallback
    except Exception:
        pass
    # 3) Fallback: scrape HTML for download link using a browser UA
    orig_ua = s.headers.get("User-Agent")
    try:
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0.0.0 Safari/537.36"
        )
        page = s.get(page_url, timeout=60).text
    finally:
        if orig_ua is not None:
            s.headers["User-Agent"] = orig_ua
    soup_page = bs4.BeautifulSoup(page, "html.parser")
    # look for download button anchor
    for a_tag in soup_page.find_all("a", id=lambda x: x and "download" in x.lower()):
        href = a_tag.get("href")
        if not href or href.strip() == "#":
            continue
        if re.match(r'^(?:https?:)?//download[0-9]*\.mediafire\.com/', href):
            link = href
            if link.startswith("//"):
                link = "https:" + link
            elif link.startswith("/"):
                link = "https://www.mediafire.com" + link
            print(f"⇱ [HTML scrape] fallback link: {link}")
            return link
    # fallback: any link to download server
    for a_tag in soup_page.find_all("a", href=True):
        href = a_tag["href"]
        if re.match(r'^(?:https?:)?//download[0-9]+\.mediafire\.com/', href):
            link = href
            if link.startswith("//"):
                link = "https:" + link
            elif link.startswith("/"):
                link = "https://www.mediafire.com" + link
            print(f"⇱ [HTML scrape] fallback link: {link}")
            return link
    # no direct link found
    raise RuntimeError(f"Direct link not found for {page_url}")

# ───── pickers ─────
def pick_region(regs):
    print("\nAVAILABLE REGIONS")
    print(tabulate([(i+1,r) for i,r in enumerate(regs)],
                   headers=["#","Region"],tablefmt="rounded_grid"))
    while True:
        ans=input("Region # or name > ").strip()
        if ans.isdigit() and 1<=int(ans)<=len(regs): return regs[int(ans)-1]
        if ans in regs: return ans
        guess,_=fuzz.extractOne(ans,regs)
        if input(f"Did you mean '{guess}'? [Y/n] ").lower() in ("","y"): return guess
r"""  # commented-out stub of old pick_links
def pick_links(files):
    table=[(i+1,s or "",landing_filename(link),area,note)
           for i,(area,link,s,note) in enumerate(files)]
    print("\nFILES")
    print(tabulate(table,headers=["#","Size","Filename","Area","Notes"],
                   tablefmt="rounded_grid"))
    raw=input("Download which files? (* for all) > ").strip().lower()
    return list(range(len(files))) if raw in ("*","all") else \
           [int(x)-1 for x in re.split(r"[,\s]+",raw) if x.isdigit() and 1<=int(x)<=len(files)]
"""

def pick_links(files):
    console = Console()
    term_w  = shutil.get_terminal_size((120, 20)).columns

    tbl = Table(show_lines=True)
    tbl.add_column("#", style="bold", width=4, justify="right")
    tbl.add_column("Size", width=10)
    tbl.add_column("Filename", overflow="fold")      # auto‑wrap
    tbl.add_column("Area", overflow="fold")
    tbl.add_column("Notes", overflow="fold")

    for i, (area, link, sz, note) in enumerate(files, 1):
        tbl.add_row(
            str(i),
            sz or "",
            landing_filename(link),
            area,
            note
        )

    console.print()
    console.print(tbl, width=term_w)   # width hint = current terminal
    console.print()

    raw = console.input("Download which files? (* for all) > ").strip().lower()
    return list(range(len(files))) if raw in ("*", "all") else [
        int(x) - 1
        for x in re.split(r"[,\s]+", raw)
        if x.isdigit() and 1 <= int(x) <= len(files)
    ]


# ───── fetch ─────
def fetch(url,dest,sess,done):
    fname = os.path.basename(urlparse(url).path)
    # skip if already downloaded
    final = os.path.join(dest, fname)
    if (dest, fname) in done and os.path.exists(final):
        return
    done.add((dest, fname))
    # indicate which file and URL we're downloading
    print(f"⇣ {fname}  URL: {url}")
    # download into temporary file
    tmp = final + ".tmp"
    with sess.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        bar = tqdm.tqdm(total=total, unit="B", unit_scale=True)
        with open(tmp, "wb") as fp:
            for chunk in r.iter_content(1 << 20):
                fp.write(chunk)
                bar.update(len(chunk))
        bar.close()
    # move to final filename
    try:
        os.replace(tmp, final)
    except Exception:
        os.rename(tmp, final)
    # if zip, extract and remove (with deflate64 support via libarchive fallback)
    if final.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(final) as z:
                z.extractall(dest)
        except (NotImplementedError, zipfile.BadZipFile) as e:
            # fallback to libarchive for unsupported ZIP compression method (e.g., deflate64)
            try:
                import libarchive.public as libarchive
            except ImportError:
                raise RuntimeError(
                    f"Failed to extract {final}: unsupported ZIP compression ({e}). "
                    "Install 'libarchive-c' (pip install libarchive-c) to enable deflate64 ZIP support."
                )
            for entry in libarchive.file_reader(final):
                outpath = os.path.join(dest, entry.pathname)
                if entry.isdir:
                    os.makedirs(outpath, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(outpath), exist_ok=True)
                    with open(outpath, "wb") as f:
                        for block in entry.get_blocks():
                            f.write(block)
        # remove archive after extraction
        os.remove(final)

# ───── main ─────
def main():
    # parse CLI and select source if needed
    args = cli()
    if args.source is None:
        args.source = pick_source()
    # create HTTP session
    sess = make_session(args)
    # select scraping function based on source
    if args.source == 'savinggrace':
        tree = scrape_savinggrace(sess)
    else:
        tree = scrape(sess)
    # prepare output directory, grouping by source
    root = os.path.abspath(args.charts_dir)
    source_dir = 'ChartLocker' if args.source == 'chartlocker' else 'SavingGrace'
    base_dir = os.path.join(root, source_dir)
    os.makedirs(base_dir, exist_ok=True)
    # select region and files
    region = pick_region(list(tree))
    files=tree[region]
    picks=pick_links(files)
    done=set()
    for i in picks:
        area, link, _, _ = files[i]
        # construct folder under base_dir/region_mbtiles/area_slug
        region_dir = f"{region.replace(' ','_')}_mbtiles"
        folder = os.path.join(base_dir, region_dir, slugify(area))
        os.makedirs(folder, exist_ok=True)
        # determine expected filenames
        basename = landing_filename(link)
        final_path = os.path.join(folder, basename)
        tmp_path = final_path + ".tmp"
        # skip if already downloaded
        if os.path.exists(final_path):
            print(f"⇢ Skipping {basename}: already present")
            done.add((folder, basename))
            continue
        # remove any stale temp file to allow fresh download
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        # resolve direct-download URL and fetch
        # fetch differently depending on source
        try:
            if args.source == 'savinggrace':
                # direct HTTP download
                fetch(link, folder, sess, done)
            else:
                # MediaFire URL resolution
                direct_url = mediafire_direct(link, sess)
                fetch(direct_url, folder, sess, done)
        except Exception as e:
            print("⚠", basename, e)
    print(f"\nFinished – {len(done)} file(s) downloaded into '{base_dir}'.")

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: sys.exit("\nCancelled")

