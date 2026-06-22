"""Show all videos recorded as uploaded.

Run:  ./venv/bin/python list_uploaded.py

Thin CLI shim over uploader.Ledger.
"""
from uploader import Ledger, Settings


def main():
    recs = Ledger(Settings().ledger_path).list_records()
    if not recs:
        print("No videos uploaded yet. (ledger.json is empty)")
        return
    rows = sorted(recs.values(), key=lambda r: r.get("last_uploaded", ""))
    print(f"{'WHEN':<20}  {'PLATFORMS':<20}  NAME")
    print("-" * 70)
    for r in rows:
        when = r.get("last_uploaded", "?")
        plats = ",".join(r.get("platforms", []))
        print(f"{when:<20}  {plats:<20}  {r.get('name', '?')}")
    print(f"\nTotal: {len(rows)} video(s).")


if __name__ == "__main__":
    main()
