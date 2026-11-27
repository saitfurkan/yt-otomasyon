import json, urllib.parse, urllib.request, html, re, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commons
for q in ["cinematic ambient", "dark ambient", "suspense soundtrack", "Kevin MacLeod", "documentary background music", "drone ambient music"]:
    p = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} filetype:audio",
        "gsrnamespace": "6", "gsrlimit": "20", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata|mediatype"})
    raw = commons._get(commons.API + "?" + p)
    pages = (json.loads(raw).get("query") or {}).get("pages") or {} if raw else {}
    print("SORGU", q, len(pages))
    for pg in pages.values():
        ii = (pg.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata") or {}
        print("  ", pg["title"][:70], "|", ii.get("mime"), "|", round(ii.get("duration", 0)), "sn |", commons._clean((md.get("LicenseShortName") or {}).get("value", "")), "|", ii.get("size"))
