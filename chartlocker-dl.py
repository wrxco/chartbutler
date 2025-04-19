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
UA   = "ChartLockerDL/0.9.1 (+https://github.com/your-repo)"

# ─────────── CLI ───────────
def cli():
    p = argparse.ArgumentParser(description="Download files from The Chart Locker")
    p.add_argument("--cookies");  p.add_argument("--email");  p.add_argument("--password")
    return p.parse_args()

# ───── session ─────
def make_session(a):
    s=requests.Session(); s.headers["User-Agent"]=UA
    if a.cookies and os.path.isfile(a.cookies):
        for ln in open(a.cookies,encoding="utf-8"):
            if ln.startswith("#") or not ln.strip(): continue
            dom,_,path,sec,_,name,val=ln.strip().split("\t")
            s.cookies.set(name,val,domain=dom,path=path,secure=(sec.lower()=="true"))
    elif a.email and a.password:
        try:
            from mediafire import MediaFireApi
            tok=MediaFireApi().user_get_session_token(a.email,a.password,"42511")
            s.headers["Authorization"]="Bearer "+tok["session_token"]
        except Exception as e: print("⚠ MediaFire login:",e)
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
    rows=[]
    for tbl in tables:
        for tr in tbl.find_all("tr"):
            links=tr.find_all("a", href=lambda u:u and"mediafire.com"in u)
            if not links: continue
            tds=[td.get_text(" ",strip=True) for td in tr.find_all("td")]
            area=tds[1] if len(tds)>1 else tds[0]
            note=td_notes(tds)
            sizes=[human_size(x) for x in tds if re.search(r'(MB|GB)',x)]
            for i,a in enumerate(links):
                size=sizes[i] if i<len(sizes) else ""
                rows.append((area,a["href"],size,note))
    return rows

def mediafire_direct(url,s):
    m=re.search(r'href="(https://download[^"]+)"',s.get(url,timeout=60).text)
    if not m: raise RuntimeError("Direct link not found")
    return m.group(1)

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
"""
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
    fname=os.path.basename(urlparse(url).path)
    if (dest,fname) in done: return
    done.add((dest,fname))
    print(f"⇣ {fname}")
    path=os.path.join(dest,fname)
    with sess.get(url,stream=True,timeout=60) as r:
        r.raise_for_status()
        bar=tqdm.tqdm(total=int(r.headers.get("content-length",0)),
                      unit="B",unit_scale=True)
        with open(path,"wb") as fp:
            for chunk in r.iter_content(1<<20): fp.write(chunk); bar.update(len(chunk))
        bar.close()
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z: z.extractall(dest)
        os.remove(path)

# ───── main ─────
def main():
    args=cli(); sess=make_session(args); tree=scrape(sess)
    region=pick_region(list(tree))
    files=tree[region]
    picks=pick_links(files)
    done=set()
    for i in picks:
        area,link,_,_=files[i]
        folder=os.path.join(f"{region.replace(' ','_')}_mbtiles", slugify(area))
        os.makedirs(folder,exist_ok=True)
        try: fetch(mediafire_direct(link,sess),folder,sess,done)
        except Exception as e: print("⚠",landing_filename(link),e)
    print(f"\nFinished – {len(done)} file(s) downloaded into '{os.getcwd()}'.")

if __name__=="__main__":
    try: main()
    except KeyboardInterrupt: sys.exit("\nCancelled")

