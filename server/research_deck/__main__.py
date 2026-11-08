"""python -m research_deck  →  serve the dashboard on 127.0.0.1:8765 (loopback only)."""
import argparse

import uvicorn

from . import config, offloaded


def main() -> None:
    offloaded.download_on_read()        # first: project files may be ones iCloud has offloaded (research_deck/offloaded.py)
    parser = argparse.ArgumentParser(prog="research_deck")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("Research Deck drives local agents and writes files; it only listens on loopback.")
    import os
    os.environ["RD_HOST"], os.environ["RD_PORT"] = args.host, str(args.port)   # so a --reload child sees them too
    config.HOST, config.PORT = args.host, args.port
    config.ALLOWED_ORIGINS |= {f"http://{args.host}:{args.port}", f"http://localhost:{args.port}"}
    # Open event streams must not hold shutdown forever; the lifespan hook then stops every agent process.
    uvicorn.run("research_deck.app:app", host=args.host, port=args.port, reload=args.reload, timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
