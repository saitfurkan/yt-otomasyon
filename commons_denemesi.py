import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commons
for q, v in commons.fetch(["Brentford Community Stadium", "Griffin Park Brentford", "MCH Arena Herning", "Wembley Stadium", "Kew Bridge station"], "ornekler/commons", 2).items():
    print("SORGU", q, len(v))
    for x in v:
        print("   KREDI", x["credit"][:220], os.path.getsize(x["path"]))
