"""Quick health check: is the app actually talking to Qdrant?

Reads your .env, connects to the configured Qdrant cluster, and lists every
collection with its point (vector) count. Run it after the bot has handled a few
messages — you should see counts climbing in collections like 'conversations'.

Run:
    .venv\\Scripts\\python.exe scripts/check_qdrant.py     (Windows)
    python scripts/check_qdrant.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402  (also runs load_dotenv)


def main():
    print(f"VECTOR_BACKEND = {config.vector_backend!r}")
    if config.vector_backend != "qdrant":
        print("Backend is not 'qdrant' — the app is using local Chroma. "
              "Set VECTOR_BACKEND=qdrant in .env to use the cluster.")
        return
    if not config.qdrant_url:
        print("QDRANT_URL is empty — the app would fall back to local Chroma.")
        return

    print(f"QDRANT_URL    = {config.qdrant_url}")
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=config.qdrant_url, api_key=config.qdrant_api_key or None)
        cols = client.get_collections().collections
    except Exception as e:
        print(f"\n[FAIL] Could not reach Qdrant: {e}")
        print("Check the URL (keep the :6333), the API key, and that the cluster is healthy.")
        sys.exit(1)

    if not cols:
        print("\n[OK] Connected, but no collections yet. Chat with the bot a bit, "
              "then re-run — collections are created on first write.")
        return

    print(f"\n[OK] Connected. {len(cols)} collection(s):")
    total = 0
    for c in cols:
        n = client.count(c.name, exact=True).count
        total += n
        print(f"   - {c.name:<16} {n} vectors")
    print(f"\nTotal vectors in Qdrant: {total}")


if __name__ == "__main__":
    main()
