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
    p.add_argument("--query", required=True)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--doc-id", default="")
    args = p.parse_args()

    payload = {
        "group_id": args.group_id,
        "mode": "chunks_vector",
        "query": args.query,
        "top_k": int(args.top_k),
    }
    if args.doc_id.strip():
        payload["doc_id"] = args.doc_id.strip()

    out = _post_json(args.base_url, "/retrieval", payload)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
