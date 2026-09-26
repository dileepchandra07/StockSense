"""Entry point.

Locally:

    python run.py                  # http://127.0.0.1:5000

In a container or on a platform that provides ``PORT``, this binds ``0.0.0.0``
so the port is reachable from outside:

    PORT=8000 AUTO_SEED=1 python run.py

For anything beyond a demo, put it behind gunicorn instead:

    gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT --workers 1 --threads 4

One worker, not four: SQLite is a single file, and multiple processes writing
to it buy contention rather than throughput. Threads give the concurrency.
"""

import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # A platform that sets PORT expects a public bind; on a laptop, stay on
    # the loopback address so the dev server is not exposed to the network.
    default_host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    app.run(
        host=os.environ.get("HOST", default_host),
        port=port,
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
    )
