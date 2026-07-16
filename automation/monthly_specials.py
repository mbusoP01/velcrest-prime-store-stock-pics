"""
Monthly specials swap — runs on a free GitHub Actions cron.
Publishes the current month's bundles (creating them if missing, else setting
them active) and drafts every other month's bundles, all via the Shopify Admin
API. Idempotent: safe to run repeatedly.

Env:
  SHOPIFY_STORE   e.g. velcrest-prime   (the *.myshopify.com subdomain)
  SHOPIFY_TOKEN   Admin API access token from a custom app (scope: write_products)
  SPECIALS_MONTH  optional YYYY-MM to force a month (blank = today's month)
"""
import os, json, time, datetime, urllib.request, urllib.error

STORE = os.environ["SHOPIFY_STORE"]
TOKEN = os.environ["SHOPIFY_TOKEN"]
API = f"https://{STORE}.myshopify.com/admin/api/2024-10"
HDR = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}
HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLES = os.path.join(HERE, "bundles")


def api(method, path, body=None, retries=3):
    for attempt in range(retries):
        req = urllib.request.Request(
            API + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=HDR, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                time.sleep(0.6)  # stay under 2 req/s REST limit
                return json.loads(r.read() or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 * (attempt + 1)); continue
            print(f"  ! {method} {path} -> {e.code} {e.read()[:200]}")
            raise
    return {}


def find_by_handle(handle):
    ps = api("GET", f"/products.json?handle={handle}&fields=id,handle,status").get("products", [])
    return ps[0] if ps else None


def product_body(p, status):
    return {"product": {
        "handle": p["handle"], "title": p["title"], "body_html": p["body_html"],
        "vendor": p["vendor"], "product_type": p["product_type"], "tags": p["tags"],
        "status": status,
        "images": [{"src": p["image_src"]}] if p.get("image_src") else [],
        "variants": [{
            "price": p["price"], "compare_at_price": p["compare_at_price"],
            "sku": p["sku"], "inventory_management": None,
            "requires_shipping": True, "taxable": True,
        }],
    }}


def main():
    month = os.environ.get("SPECIALS_MONTH", "").strip() or datetime.date.today().strftime("%Y-%m")
    months = json.load(open(os.path.join(BUNDLES, "_months.json")))
    print(f"Target month: {month} | known months: {months}")

    cur_path = os.path.join(BUNDLES, f"{month}.json")
    current_handles = set()

    # 1) publish/upsert the current month's bundles as ACTIVE
    if os.path.exists(cur_path):
        for p in json.load(open(cur_path)):
            current_handles.add(p["handle"])
            existing = find_by_handle(p["handle"])
            if existing:
                b = product_body(p, "active"); b["product"]["id"] = existing["id"]
                api("PUT", f"/products/{existing['id']}.json", b)
                print(f"  active (updated): {p['handle']}")
            else:
                api("POST", "/products.json", product_body(p, "active"))
                print(f"  active (created): {p['handle']}")
    else:
        print(f"  no bundle file for {month} — publishing nothing, only retiring old")

    # 2) draft every OTHER month's bundles (only our known handles, no full scan)
    for mk in months:
        if mk == month:
            continue
        for p in json.load(open(os.path.join(BUNDLES, f"{mk}.json"))):
            if p["handle"] in current_handles:
                continue
            existing = find_by_handle(p["handle"])
            if existing and existing.get("status") == "active":
                api("PUT", f"/products/{existing['id']}.json",
                    {"product": {"id": existing["id"], "status": "draft"}})
                print(f"  drafted: {p['handle']}")
    print("Done.")


if __name__ == "__main__":
    main()
