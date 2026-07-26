# Deploying Flashbang on Zo Computer

Zo gives you a persistent cloud machine — running Flashbang there makes the
dashboard reachable from any device (your $50 sponsor credits cover it).

1. **Get the code up.** Push this repo to a private GitHub remote, then on
   the Zo machine: `git clone <your repo> && cd Flashbang-frameworks`
   (or upload the folder through Zo's file manager — exclude `flashbang/`,
   the venv rebuilds).
2. **Install:**
   ```
   python -m venv venv
   venv/bin/pip install -r requirements.txt
   ```
3. **Configure:** create `.env` with your `OPENAI_API_KEY` (plus any
   integrations from INTEGRATIONS.md).
4. **Data:** copy your local `flashbang.db` (and `uploads/`) up if you want
   your existing courses; otherwise it starts fresh. Run
   `venv/bin/python backfill_embedding.py` once to rebuild the Chroma index
   (first run downloads the ~80 MB local embedding model).
5. **Run:** `PORT=8080 venv/bin/python server.py` — the server binds
   0.0.0.0, so expose that port via Zo's port-forwarding/preview to get a
   URL.
6. **Keep it running:** use Zo's process manager / a `tmux` session so it
   survives disconnects.

**Security note:** Flashbang has no authentication. Keep the exposed URL
private (Zo's authenticated preview links are fine; a public URL is not) —
anyone with the link can read your notes and burn your API credits.
