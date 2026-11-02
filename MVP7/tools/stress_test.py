"""
Concurrency stress test: many people saving at once.

!! This CREATES TEST DATA (codes, a user, categories, a dropdown option) and
!! changes the Master password. Run it ONLY against a throwaway copy of the app
!! started on a FRESH database, never against the real one.

How to use (from the app folder):
    # 1. start a throwaway copy on a fresh database, with a known first password
    INITIAL_ADMIN_PASSWORD=Setup-Pass-4455 PORT=5300 python app.py
    #    (Windows PowerShell:  $env:INITIAL_ADMIN_PASSWORD="Setup-Pass-4455"; $env:PORT="5300"; python app.py)
    # 2. in a second window
    pip install requests
    python tools/stress_test.py http://127.0.0.1:5300 Setup-Pass-4455

What "good" looks like: every scenario shows only 200 and 409 (a clean
"already exists"), never 500 / 503 / EXC; S1 reports exactly 001..040 with no
gaps; S2, S4 and S6 report exactly one success.

To test your real hosting stack (waitress, reverse proxy), point it at a
throwaway instance started the same way you will run production. Targets
other than this computer need --force.
"""
import sys
from urllib.parse import urlparse

if len(sys.argv) < 3:
    raise SystemExit("usage: python tools/stress_test.py BASE_URL INITIAL_MASTER_PASSWORD [--force]")
_host = urlparse(sys.argv[1]).hostname
if _host not in ("localhost", "127.0.0.1", "::1") and "--force" not in sys.argv:
    raise SystemExit(f"Refusing to run against {_host}: this creates test data. Use a local throwaway copy, or add --force if you are certain.")

import threading, collections, requests, time

BASE, INITIAL = sys.argv[1].rstrip("/"), sys.argv[2]
NEW_PW = "Stress-Admin-2026"

# ---- sign in once, choose a real password, keep the session cookie
s0 = requests.Session()
s0.post(BASE + "/login", data={"username": "Master", "password": INITIAL})
s0.post(BASE + "/change-password", data={"current_password": INITIAL, "new_password": NEW_PW, "confirm_password": NEW_PW})
assert s0.get(BASE + "/api/me").status_code == 200, "setup sign-in failed"
cookies = s0.cookies.get_dict()


def new_session():
    s = requests.Session()
    s.cookies.update(cookies)
    return s


def blast(jobs):
    """jobs: list of (method, path, json). All fired together via a barrier."""
    results = [None] * len(jobs)
    barrier = threading.Barrier(len(jobs))

    def worker(i):
        s = new_session()
        method, path, body = jobs[i]
        barrier.wait()
        try:
            r = s.request(method, BASE + path, json=body, timeout=60)
            try:
                payload = r.json()
            except ValueError:
                payload = {"_raw": r.text[:80]}
            results[i] = (r.status_code, payload)
        except Exception as e:  # connection reset, timeout...
            results[i] = ("EXC", {"error": repr(e)[:80]})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(jobs))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results


def summary(results):
    return dict(collections.Counter(str(r[0]) for r in results))


def errors(results, limit=3):
    seen = []
    for code, body in results:
        if code not in (200, 409):
            seen.append((code, body.get("error") or body.get("_raw")))
    return seen[:limit]


print(f"Target: {BASE}\n")

# S1: 40 people create the same sequence-numbered code at once
r = blast([("POST", "/api/codes", {"category": "busbar", "values": {"project_code": "JEVBP", "material": "AL", "sub_type": "SO"}})] * 40)
codes = sorted(x[1]["code"] for x in r if x[0] == 200)
expected = [f"JEVBP-04-AL-SO-{i:03d}" for i in range(1, 41)]
print("S1  40 simultaneous busbar codes (each should get its own next number)")
print("    status counts:", summary(r))
print("    got", len(codes), "codes | all unique:", len(set(codes)) == len(codes), "| exactly 001..040 with no gaps:", codes == expected)
print("    first failures:", errors(r) or "none")

# S2: 25 people create the identical fixed code at once
r = blast([("POST", "/api/codes", {"category": "cell", "values": {"supplier": "EVE", "capacity": "105"}})] * 25)
print("\nS2  25 simultaneous identical cell codes (exactly 1 should succeed, the rest a clean 'duplicate')")
print("    status counts:", summary(r), "| exactly one success:", sum(1 for x in r if x[0] == 200) == 1)
print("    unexpected failures:", errors(r) or "none")

# S3: mixed categories, 8 threads each
mix = []
for cat, vals in [("general", {"project_code": "JEVBP", "category_code": "01"}),
                  ("drawing", {"project_code": "JEVBP", "doc_type": "DRW"}),
                  ("insulation", {"project_code": "JEVBP", "material_type": "GKT"}),
                  ("electrical", {"project_code": "JEVBP", "part_type": "CON"}),
                  ("busbar", {"project_code": "JBESS", "material": "CU", "sub_type": "FL"})]:
    mix += [("POST", "/api/codes", {"category": cat, "values": vals})] * 8
r = blast(mix)
codes = [x[1]["code"] for x in r if x[0] == 200]
print("\nS3  40 simultaneous codes across 5 categories")
print("    status counts:", summary(r), "| all unique:", len(set(codes)) == len(codes), "| count:", len(codes))
print("    unexpected failures:", errors(r) or "none")

# S4: 20 admins create the same username at once
r = blast([("POST", "/api/users", {"username": "samename", "password": "Temp-Pass-12345", "role": "User", "access": ["home"]})] * 20)
print("\nS4  20 simultaneous 'create user samename'")
print("    status counts:", summary(r), "| exactly one success:", sum(1 for x in r if x[0] == 200) == 1)
print("    unexpected failures:", errors(r) or "none")

# S5: same custom category defined 10 times at once
r = blast([("POST", "/api/categories", {"label": "Thermal Pad", "prefix": "JEVBP", "fields": [
    {"label": "Thickness", "kind": "choice", "choices_raw": "1MM,2MM"}, {"label": "Sequence", "kind": "auto"}]})] * 10)
print("\nS5  10 simultaneous 'create category Thermal Pad'")
print("    status counts:", summary(r))
print("    unexpected failures:", errors(r) or "none")

# S6: same dropdown option added 10 times at once
r = blast([("POST", "/api/categories/cell/fields/supplier/options", {"code": "NEWCO", "label": "NewCo"})] * 10)
print("\nS6  10 simultaneous 'add option NEWCO'")
print("    status counts:", summary(r), "| exactly one success:", sum(1 for x in r if x[0] == 200) == 1)
print("    unexpected failures:", errors(r) or "none")

# S7: readers stay responsive while writers are busy
mixed = [("GET", "/api/codes", None)] * 15 + [("POST", "/api/codes", {"category": "drawing", "values": {"project_code": "JBESS", "doc_type": "3DM"}})] * 15
t0 = time.time()
r = blast(mixed)
print("\nS7  15 readers + 15 writers at once")
print("    status counts:", summary(r), f"| finished in {time.time()-t0:.1f}s")
print("    unexpected failures:", errors(r) or "none")
