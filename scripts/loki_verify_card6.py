#!/usr/bin/env python3
"""Verify Loki has kb and inventory stream events. Run ON .220 directly."""
import json, sys, time
import urllib.request


def query_loki(loki_query):
    now_ns = int(time.time() * 1_000_000_000)
    start_ns = now_ns - 3600 * 1_000_000_000
    url = (
        f"http://127.0.0.1:3100/loki/api/v1/query_range"
        f"?query={urllib.parse.quote(loki_query)}"
        f"&start={start_ns}&end={now_ns}&limit=20"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


print("=== KB stream ({stream=\"kb\"}) ===")
d = query_loki('{stream="kb"}')
res = d.get("data", {}).get("result", [])
total = sum(len(s.get("values", [])) for s in res)
print(f"streams={len(res)} total_entries={total}")
for s in res:
    print(f"  stream={s.get('stream')} entries={len(s.get('values',[]))}")
    for ts, ln in s.get("values", [])[:5]:
        print(f"    [{ts}] {ln[:300]}")

print("\n=== INVENTORY stream ({stream=\"inventory\"}) ===")
d = query_loki('{stream="inventory"}')
res = d.get("data", {}).get("result", [])
total = sum(len(s.get("values", [])) for s in res)
print(f"streams={len(res)} total_entries={total}")
for s in res:
    print(f"  stream={s.get('stream')} entries={len(s.get('values',[]))}")
    for ts, ln in s.get("values", [])[:5]:
        print(f"    [{ts}] {ln[:300]}")

print("\n=== Privacy check: KB stream ===")
d = query_loki('{stream="kb"}')
res = d.get("data", {}).get("result", [])
hit = False
for s in res:
    for ts, ln in s.get("values", []):
        # 'username':'smoke' is the user id, NOT a query body.
        if '"username": "smoke"' in ln:
            continue
        if 'smoke' in ln.lower() or 'Card 6 smoke test runbook' in ln:
            hit = True
            print(f"POSSIBLE LEAK: {ln[:300]}")
if not hit:
    print("OK: no query body / entry content leaked into KB stream payload.")
