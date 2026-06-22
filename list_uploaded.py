"""Show all videos recorded as uploaded, grouped by platform.

Run:  ./venv/bin/python list_uploaded.py

Thin CLI shim over uploader.Ledger.
"""
from uploader import Ledger, Settings


def main():
    data = Ledger(Settings().ledger_path).list_records()
    total = sum(len(v) for v in data.values())
    if not total:
        print("No videos uploaded yet. (ledger.json is empty)")
        return

    for platform in sorted(data):
        recs = data[platform]
        if not recs:
            continue
        print(f"\n=== {platform.upper()} ({len(recs)}) ===")
        print(f"{'WHEN':<20}  NAME")
        print("-" * 60)
        for r in sorted(recs.values(), key=lambda r: r.get("last_uploaded", "")):
            print(f"{r.get('last_uploaded', '?'):<20}  {r.get('name', '?')}")

    print(f"\nTotal: {total} upload(s) across {len([p for p in data if data[p]])} platform(s).")


if __name__ == "__main__":
    main()
