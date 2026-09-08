import sys, io, urllib.request, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with urllib.request.urlopen("http://localhost:8000/api/models", timeout=10) as r:
    d = json.loads(r.read())

print(f"current: {d['current_provider']} / {d['current_model']}")
print(f"\nconfigured providers:")
for p in d['providers']:
    if p['configured']:
        print(f"  {p['id']:12s} ({p['label']:14s}) {len(p['models'])} models")
        for m in p['models'][:3]:
            print(f"      - {m}")
        if len(p['models']) > 3:
            print(f"      - ... +{len(p['models']) - 3} more")
print(f"\ntotal providers: {len(d['providers'])}")

# test /api/model/switch
print("\n=== test POST /api/model/switch ===")
req = urllib.request.Request(
    "http://localhost:8000/api/model/switch",
    data=json.dumps({"provider": "minimax", "model_name": "MiniMax-M2.7"}).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        r2 = json.loads(r.read())
        print(f"switch result: {r2}")
except urllib.error.HTTPError as e:
    print(f"switch HTTP {e.code}: {e.read().decode()[:200]}")
