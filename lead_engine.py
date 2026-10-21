"""Local lead engine (service backend + free daily dataset).

Usage:
  python service/lead_engine.py --keywords AI,saas --max 40 --out leads.csv
Sources: Hacker News Show HN (open API). Enriches each site with emails, socials, pixels.
"""
import argparse
import csv
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}
EMAIL = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,10}\b")
BAD_EXT = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".css", ".js", ".woff", ".woff2")
BAD_DOM = ("sentry", "example.", "wixpress", "domain.com", "yourdomain", "email.com", "@company.", "you@", "your@", "name@", "user@", "username@")


def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def show_hn(n, kws):
    url = f"https://hn.algolia.com/api/v1/search_by_date?tags=show_hn&hitsPerPage={min(n * 4, 200)}"
    hits = json.loads(fetch(url))["hits"]
    out = []
    for h in hits:
        u = h.get("url")
        t = re.sub(r"^Show HN:\s*", "", h.get("title") or "").strip()
        if not u or "github.com" in u:
            continue
        if kws and not any(k in t.lower() for k in kws):
            continue
        out.append({"name": t.split(" – ")[0].split(" - ")[0][:80], "tagline": t, "maker": h.get("author"),
                    "website": u, "hn": f"https://news.ycombinator.com/item?id={h['objectID']}",
                    "date": (h.get("created_at") or "")[:10]})
        if len(out) >= n:
            break
    return out


def enrich(row):
    row.update(emails="", twitter="", linkedin="", pixels="", missing="", score=30, pitch="")
    try:
        html = fetch(row["website"])
        low = html.lower()
        em = []
        for e in EMAIL.findall(html):
            e = e.lower()
            if e.endswith(BAD_EXT) or any(b in e for b in BAD_DOM) or e in em:
                continue
            em.append(e)
        row["emails"] = ";".join(em[:3])
        tw = re.findall(r"https?://(?:twitter\.com|x\.com)/([A-Za-z0-9_]{3,25})", html)
        li = re.findall(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/([A-Za-z0-9_-]+)", html)
        row["twitter"] = f"https://x.com/{tw[0]}" if tw else ""
        row["linkedin"] = f"https://linkedin.com/company/{li[0]}" if li else ""
        inst, miss = [], []
        for label, keys in (("Meta Pixel", ("connect.facebook.net", "fbq(")),
                            ("Google Analytics/GTM", ("googletagmanager.com", "google-analytics.com", "gtag(")),
                            ("TikTok Pixel", ("analytics.tiktok.com", "ttq."))):
            (inst if any(k in low for k in keys) else miss).append(label)
        row["pixels"], row["missing"] = ";".join(inst), ";".join(miss)
        s = 30 + (25 if em else 0) + (15 if tw or li else 0) + (15 if "Google Analytics/GTM" in inst else 0) + (15 if miss else 0)
        row["score"] = min(s, 100)
        if "Meta Pixel" in miss:
            row["pitch"] = f"Congrats on launching {row['name']}! No Meta Pixel detected - retargeting launch visitors could lift signups."
        else:
            row["pitch"] = f"Congrats on launching {row['name']}! Happy to help with post-launch distribution."
    except Exception as ex:
        row["pitch"] = f"(site unreachable: {type(ex).__name__})"
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="")
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--out", default="leads.csv")
    a = ap.parse_args()
    kws = [k.strip().lower() for k in a.keywords.split(",") if k.strip()]
    rows = show_hn(a.max, kws)
    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(enrich, rows))
    rows.sort(key=lambda r: -r["score"])
    cols = ["name", "tagline", "maker", "website", "emails", "twitter", "linkedin", "pixels", "missing", "score", "pitch", "hn", "date"]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} leads -> {a.out} | with email: {sum(1 for r in rows if r['emails'])}")


if __name__ == "__main__":
    main()
