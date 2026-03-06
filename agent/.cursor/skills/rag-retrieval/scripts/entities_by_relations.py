import argparse
import json

import requests


def _post_json(base_url: str, path: str, payload: dict):
    url = f"{base_url.rstrip('/')}{path}"
    r = requests.post(url, json=payload, timeout=300)
    r.raise_for_status()
    return r.json()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8080")
    p.add_argument("--group-id", required=True)
    p.add_argument("--relation-ids", default="", help="Comma-separated relation ids")
    p.add_argument("--relation-triples-json", default="", help="JSON list of relation triples (dict)")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--doc-id", default="")
    args = p.parse_args()

    payload = {
        "group_id": args.group_id,
        "mode": "entities_by_relations",
        "limit": int(args.limit),
    }
    if args.doc_id.strip():
        payload["doc_id"] = args.doc_id.strip()

    relation_ids = [s.strip() for s in (args.relation_ids or "").split(",") if s.strip()]
    if relation_ids:
        payload["relation_ids"] = relation_ids

    if args.relation_triples_json.strip():
        payload["relation_triples"] = json.loads(args.relation_triples_json)

    out = _post_json(args.base_url, "/retrieval", payload)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
