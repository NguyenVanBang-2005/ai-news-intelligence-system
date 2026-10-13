"""Seed the configured database with part of the synthetic corpus via the real ingestion code.

Only the HTTP transport is mocked (the SSRF guard rejects private hosts, so a feed server
inside Docker cannot be used); parsing, cleaning, analysis and PostgreSQL writes are real.
Run inside the API container, after copying ai_corpus.py next to this file:

    docker cp tests/fixtures/ai_corpus.py <api>:/tmp/ai_corpus.py
    docker cp tests/e2e/seed_corpus.py <api>:/tmp/seed_corpus.py
    docker exec <api> python /tmp/seed_corpus.py --source "Corpus A" --groups gen,robotics

Selectors: --groups (group names), --slugs (link suffixes), --all.
"""

import argparse
import json
import socket
import sys

import httpx

sys.path.insert(0, "/tmp")
sys.path.insert(0, ".")

import ai_corpus  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.repositories.source import SourceRepository  # noqa: E402
from app.schemas.source import SourceCreate  # noqa: E402
from app.services.feed import FeedClient  # noqa: E402
from app.services.ingestion import IngestionService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--groups", default="")
    parser.add_argument("--slugs", default="")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    groups = {g for g in args.groups.split(",") if g}
    slugs = {s for s in args.slugs.split(",") if s}
    items = [
        item for item in ai_corpus.ALL_ITEMS
        if args.all or item["group"] in groups or item["link"].rsplit("/", 1)[-1] in slugs
    ]
    feed_url = f"https://feeds.example/{args.source.lower().replace(' ', '-')}.xml"
    body = ai_corpus.render_rss(items, title=args.source)

    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, port, *a, **k):  # fake DNS only for the synthetic feed host
        if host == "feeds.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        return real_getaddrinfo(host, port, *a, **k)

    socket.getaddrinfo = getaddrinfo
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    client = FeedClient(15, transport=transport)
    with SessionLocal() as db:
        repo = SourceRepository(db)
        existing = next((s for s in repo.list() if s.feed_url == feed_url), None)
        source = existing or repo.create(SourceCreate(name=args.source, feed_url=feed_url))
        result = IngestionService(db, feed_client=client).run(source.id)
        print(json.dumps({"source_id": source.id, "items_in_feed": len(items),
                          **result.model_dump()}))


if __name__ == "__main__":
    main()
