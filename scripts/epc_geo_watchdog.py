#!/usr/bin/env python3
"""EPC Geo Watchdog — alerts if any active ad set targets outside Florida"""
import urllib.request, json, sys, os

CONFIG_PATH = os.path.expanduser("~/epc-webhook/config.json")
try:
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    TOKEN = cfg.get("PAGE_ACCESS_TOKEN") or cfg.get("SYSTEM_TOKEN", "")
except Exception as e:
    print(f"ERROR reading config: {e}")
    sys.exit(1)

if not TOKEN:
    print("ERROR: No token found in config.json")
    sys.exit(1)

ADACCOUNT = "act_20032154"

url = (
    f"https://graph.facebook.com/v19.0/{ADACCOUNT}/adsets"
    f"?fields=id,name,targeting,daily_budget"
    f"&filtering=[{{\"field\":\"adset.effective_status\",\"operator\":\"IN\",\"value\":[\"ACTIVE\"]}}]"
    f"&access_token={TOKEN}"
)

try:
    resp = urllib.request.urlopen(url, timeout=15)
    data = json.loads(resp.read())
except urllib.error.HTTPError as e:
    err = e.read().decode()
    if "190" in err or "token" in err.lower():
        # Token expired — exit silently (don't spam Travis)
        sys.exit(0)
    print(f"HTTP ERROR: {err}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

# Adsets that are INTENTIONALLY nationwide (B2B products, not homeowner solar)
NATIONWIDE_WHITELIST = [
    "52552078132536",  # Solar Installers — Nationwide B2B (Solar Labels product)
]

alerts = []
for adset in data.get("data", []):
    name = adset.get("name", "?")
    adset_id = adset.get("id", "")
    geo = adset.get("targeting", {}).get("geo_locations", {})

    # Skip whitelisted nationwide B2B adsets
    if adset_id in NATIONWIDE_WHITELIST:
        continue

    for region in geo.get("regions", []):
        if region.get("name") != "Florida":
            alerts.append(f"BAD REGION in '{name}': {region['name']} ({region.get('country')})")

    for city in geo.get("cities", []):
        if city.get("region") and city.get("region") != "Florida":
            alerts.append(f"BAD CITY in '{name}': {city['name']}, {city.get('region')}")

    countries = geo.get("countries", [])
    if countries:
        for c in countries:
            if c != "US":
                alerts.append(f"BAD COUNTRY in '{name}': {c}")
        if countries == ["US"]:
            alerts.append(f"WHOLE USA targeted in '{name}' — should be FL cities only!")

if alerts:
    print("🚨 EPC GEO DRIFT DETECTED — FIX NOW\n")
    for a in alerts:
        print("  •", a)
    print("\nAds are spending outside Florida. Fix at business.facebook.com/adsmanager")
else:
    sys.exit(0)
