# Talking Pet Backend

This repository contains a minimal FastAPI service used by the Talking Pet
prototype.  It glues together a few third party services to turn a static pet
photo and short script into an animated video with speech.

## Features

* **ElevenLabs Text‑to‑Speech** – generates the audio track.
* **Hailuo‑02 via Replicate** – creates an animated video from an image and
  text prompt.
* **Supabase Storage** – stores generated media and exposes public URLs.
* Simple health and debugging endpoints.

## Local development

1. Ensure [Python 3.10+](https://www.python.org/) is installed.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```
3. Set the required environment variables.  The most important are:

   * `ELEVEN_API_KEY`
   * `SUPABASE_URL`
   * `SUPABASE_SERVICE_ROLE`
   * `REPLICATE_API_TOKEN`

   Optional variables include `ALLOWED_ORIGIN`, `SUPABASE_BUCKET`,
   `TTS_OUTPUT_FORMAT` and `TTS_MAX_CHARS`.
4. Run the development server:

   ```bash
   uvicorn main:app --reload
   ```

## API overview

| Method | Path               | Description                               |
| ------ | ------------------ | ----------------------------------------- |
| GET    | `/health`          | Basic health check                        |
| POST   | `/jobs_prompt_only`| Create a video from image and prompt      |
| POST   | `/jobs_prompt_tts` | Create a video with TTS audio             |
| POST   | `/debug/head`      | Retrieve headers for a remote resource    |

Each POST endpoint accepts JSON bodies as defined by the Pydantic models in
`main.py`.

## Deployment

The included `render.yaml` describes a simple configuration for deploying the
service on [Render](https://render.com/).  You can adapt it for other hosting
providers if needed.

