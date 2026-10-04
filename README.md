# Marvel Battlefield AI backend

Single FastAPI monolith for Comic Vine proxy endpoints and the LangChain Marvel assistant. It does not implement MCP.

## Run locally

1. Use Python 3.12 or newer and create a virtual environment in `backend-ai/.venv`.
2. Install `requirements.txt` and copy `.env.example` to `.env`.
3. Set `COMIC_VINE_API_KEY`. To enable chat, also set `AI_MODEL` and `AI_API_KEY`; `AI_BASE_URL` is optional for an OpenAI-compatible provider.
4. Set `MONGODB_URI` to enable short chat memory. The service stores at most the latest 10 user/assistant messages for each conversation and refreshes its 30-day expiry after a successful answer. If MongoDB is unavailable, chat continues using request history without persistent memory.
5. Start with `python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`.
6. Check `http://localhost:8000/health`.

The Android emulator reaches the development server at `http://10.0.2.2:8000/`. For a physical device, set the Gradle property `MARVEL_API_BASE_URL` to a reachable HTTPS or local development URL. Do not put provider keys in Android configuration.

## API

- `GET /api/characters?q=&limit=20&offset=0`
- `GET /api/characters/{id}`
- `POST /api/chat` with `message`, optional `history`, and `spoiler_level` (`NONE`, `LOW`, `MEDIUM`, `HIGH`)

The character API normalizes Comic Vine fields and pagination. Chat tools query Comic Vine for character, team, story arc, issue, power, and movie information. If credentials are missing, the service returns an actionable 503 response without exposing configuration values.

## Tests

Run `python -m pytest` from this directory.
