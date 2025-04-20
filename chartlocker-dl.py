#!/usr/bin/env python3
# chartlocker_dl.py · v0.9.1  (April 2025)
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
UA   = "ChartLockerDL/0.9.1 (+https://github.com/wrxco/chartlocker-dl)"

# ─────────── CLI ───────────
def cli():
    p = argparse.ArgumentParser(description="Download files from The Chart Locker")
    p.add_argument("--cookies", help="Path to cookies.txt for MediaFire session")
    p.add_argument("--email", help="MediaFire account email (optional)")
    p.add_argument("--password", help="MediaFire account password (optional)")
    p.add_argument(
        "--charts-dir",
        default=os.getcwd(),
        help="Destination directory for downloaded charts (default: current working directory)"
    )
    return p.parse_args()

# ───── session ─────
def make_session(a):
    import getpass
    # start session, set User-Agent
    s = requests.Session()
    s.headers["User-Agent"] = UA
    # authentication mode: anonymous | cookies | premium
    mode = 'anonymous'
    # 1) load cookies if file provided
    if a.cookies and os.path.isfile(a.cookies):
        for ln in open(a.cookies, encoding="utf-8"):
            if ln.startswith("#") or not ln.strip():
                continue
            dom, _, path, sec, _, name, val = ln.strip().split("\t")
            s.cookies.set(name, val, domain=dom, path=path, secure=(sec.lower() == "true"))
        mode = 'cookies'
    # 2) attempt MediaFire API login when email given
    elif a.email:
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
                # obtain and store API session token
                api = MediaFireApi()
                tok = api.user_get_session_token(
                    app_id="42511",
                    email=a.email,
                    password=a.password
                )
                # set API session and auth header
                # store session token internally for API requests
                api._session = tok
                s.headers["Authorization"] = "Bearer " + tok["session_token"]
                s.mediafire_api = api
                mode = 'premium'
            except Exception as e:
                print("⚠ MediaFire login failed:", e)
        else:
            print("⚠ MediaFire login skipped: no password provided")
    # 3) warn if password provided without email
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
    parts=urlparse(url).path.rstrip("/").split("/")
    return parts[-2] if len(parts)>=2 else "file"

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
    # always use the public '/file/' page for HTML fallbacks
    page_url = url.replace('/file_premium/', '/file/')
    # Extract quick key from URL path
    parts = urlparse(page_url).path.rstrip('/').split('/')
    quick_key = parts[-3] if len(parts) >= 3 else None
    api = getattr(s, 'mediafire_api', None)
    # 1) Try API direct link if available
    if api and quick_key:
        try:
            resp = api.file_get_links(quick_key)
            links = resp.get('links') or []
            if isinstance(links, dict):
                links = [links]
            if links:
                first = links[0]
                for key in ('direct_download', 'download_url'):
                    val = first.get(key)
                    if val:
                        return val
        except Exception:
            pass
    # 2) HTML regex fallback (unauthenticated or API fallback)
    try:
        page = s.get(page_url, timeout=60).text
        m = re.search(r'href=["\'](https://download[^"\']+)["\']', page)
        if m:
            return m.group(1)
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
    # if zip, extract and remove
    if final.lower().endswith(".zip"):
        with zipfile.ZipFile(final) as z:
            z.extractall(dest)
        os.remove(final)

# ───── main ─────
def main():
    # parse CLI and create session
    args = cli()
    sess = make_session(args)
    tree = scrape(sess)
    # prepare output directory
    base_dir = os.path.abspath(args.charts_dir)
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
        try:
            direct_url = mediafire_direct(link, sess)
            fetch(direct_url, folder, sess, done)
        except Exception as e:
            print("⚠", basename, e)
    print(f"\nFinished – {len(done)} file(s) downloaded into '{base_dir}'.")

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: sys.exit("\nCancelled")

