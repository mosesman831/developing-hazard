"""Phase 1 hello-world pod app (routes at /; ingress strips /app)."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "service": "developing-hazard"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!DOCTYPE html>
<html lang="en-GB">
<head>
  <meta charset="utf-8">
  <title>Developing Hazard</title>
</head>
<body>
  <p>An AI sits the hazard perception test.</p>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
