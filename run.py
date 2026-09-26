"""Development entry point.

    python run.py

Serves on http://127.0.0.1:5000. For anything beyond a demo, put this behind
gunicorn:  gunicorn 'app:create_app()' --bind 0.0.0.0:8000
"""

import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
    )
