# AGENTS Guidelines

## Project Overview
This FastAPI service glues together several third-party providers to turn a static pet image and short script into a talking video. It synthesizes speech with **ElevenLabs**, generates animation with **Hailuo-02 via Replicate**, and stores results in **Supabase Storage**.

## Setup Instructions
- **Python**: 3.10+
- **Install dependencies**:
  ```bash
  pip install -r requirements.txt
  ```
- **Environment variables**:
  - Mandatory: `ELEVEN_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE`, `REPLICATE_API_TOKEN`
  - Optional: `ALLOWED_ORIGIN`, `SUPABASE_BUCKET`, `TTS_OUTPUT_FORMAT`, `TTS_MAX_CHARS`
- **Run locally**:
  ```bash
  uvicorn main:app --reload
  ```

## API Reference
### `GET /health`
Simple health check.
- **Request**: none
- **Response**:
  ```json
  {"ok": true}
  ```

### `POST /jobs_prompt_only`
Create a video from an image and prompt.
- **Body – `JobPromptOnly`**:
  ```json
  {
    "image_url": "https://example.com/pet.jpg",
    "prompt": "The dog smiles",
    "seconds": 6,
    "resolution": "768p",
    "model": "minimax/hailuo-02"
  }
  ```
- **Response**:
  ```json
  {"video_url": "https://.../video.mp4"}
  ```

### `POST /jobs_prompt_tts`
Create a video and match audio.
- **Body – `JobPromptTTS`**:
  ```json
  {
    "image_url": "https://example.com/pet.jpg",
    "prompt": "The dog smiles",
    "text": "Hello!",
    "voice_id": "voice",
    "seconds": 6,
    "resolution": "768p",
    "model": "minimax/hailuo-02"
  }
  ```
- **Response**:
  ```json
  {
    "audio_url": "https://.../audio.mp3",
    "video_url": "https://.../video.mp4",
    "final_url": "https://.../final.mp4"
  }
  ```

### `POST /debug/head`
Fetch headers for a remote resource.
- **Body – `HeadRequest`**:
  ```json
  {"url": "https://example.com/file"}
  ```
- **Response**:
  ```json
  {"status": 200, "content_type": "image/jpeg", "bytes": 12345}
  ```

## Front-end Integration
- **Base URL**: `http://localhost:8000` in local dev.
- **CORS**: Controlled by `ALLOWED_ORIGIN`; defaults to `*`.
- **Status codes**: `200` success, `400` user error, `500` server/config issues.
- **Example fetch calls**:
  ```js
  const base = "http://localhost:8000";
  await fetch(`${base}/health`).then(r => r.json());

  await fetch(`${base}/jobs_prompt_only`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({image_url: "https://example.com/pet.jpg", prompt: "Hi"})
  }).then(r => r.json());
  ```

## Coding Conventions
- Use **async** functions for I/O.
- Define request bodies with **Pydantic models**.
- Keep helper utilities within `main.py`.

## Testing / Validation
- Lint with `flake8 main.py`.
- Format check with `black --check main.py`.
- Additional sanity: `python -m py_compile main.py`.
