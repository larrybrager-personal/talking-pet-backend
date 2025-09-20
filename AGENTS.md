# AGENTS Guidelines

## Project Overview
This FastAPI service glues together several third-party providers to turn a static pet image and short script into a talking video. It synthesizes speech with **ElevenLabs**, generates animation with **multiple i2v models via Replicate** (Hailuo-02, Kling v2.1, Wan v2.2), and stores results in **Supabase Storage**.

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

### `GET /models`
List supported i2v models.
- **Request**: none
- **Response**:
  ```json
  {
    "supported_models": {
      "minimax/hailuo-02": {"name": "Hailuo-02", "is_default": true},
      "kwaivgi/kling-v2.1": {"name": "Kling v2.1", "is_default": false},
      "wan-video/wan-2.2-s2v": {"name": "Wan v2.2", "is_default": false}
    },
    "default_model": "minimax/hailuo-02"
  }
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
    "model": "kuaishou/kling-video"
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

  // Check supported models
  await fetch(`${base}/models`).then(r => r.json());

  await fetch(`${base}/jobs_prompt_only`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      image_url: "https://example.com/pet.jpg", 
      prompt: "Hi",
      model: "kuaishou/kling-video"
    })
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

# AGENTS (prompts and integration guidelines)

This file documents agent-style prompts, templates, and integration patterns used when constructing prompts, scripts, and orchestrating the backend. It's intended for frontend engineers, prompt engineers, or any automated agents that prepare requests to the backend endpoints.

## Purpose
The backend expects two primary flows:

- Prompt-only: create a short talking animation from `image_url` + `prompt`.
- Prompt+TTS: create animation and synthesize speech from `text` + `voice_id`, then mux and upload the final MP4.

These flows are driven by concise prompt and script text. Use the templates below to generate reliable results.

## Agent roles

- Prompt Author (Human / LLM): Produces the short animation prompt describing the emotion, mouth movement, head tilt, eye direction, and any accessory movement.
- Script Writer (Human / LLM): Produces short spoken text for TTS. Keep it under `TTS_MAX_CHARS` and prefer 1-3 short sentences.
- Uploader (Client): Calls our `/jobs_prompt_only` or `/jobs_prompt_tts` endpoints and handles returned URLs.

## Prompt templates (for multiple i2v models)
Keep prompts short and concrete. Include style cues and motion intent. Different models may respond differently to prompting styles:

Template 1 — friendly greeting:

"A friendly golden retriever smiles, blinks, and tilts its head to the right while speaking gently. Slight ear movement, natural mouth shapes synced to speech, photorealistic style."

Template 2 — excited bark:

"Small terrier jumps slightly, wags tail, opens mouth in a quick excited bark. Eyes wide, playful expression, short energetic motion loops."

Template 3 — subtle mouth movement for voiceover:

"Calm cat looks at camera, subtle lip sync to a speaking voice, small eyebrow and ear twitches, natural breathing motion."

Notes:
- Avoid overly long prompts — keep under 1–2 sentences.
- Mention the first frame reference (the `image_url` will be used by the model).

## Script / TTS guidelines
- Keep scripts brief. Ten to twenty words perform best for short animations.
- Prefer natural spoken phrasing; include punctuation to help TTS prosody.
- Avoid special characters and emojis.
- Stay below `TTS_MAX_CHARS` (default 600).

Example scripts:
- "Hi, I'm Charlie! Want to play?"
- "Don't forget your walk at 5pm."

## Example interaction flow (frontend)
1. Check available models (optional):
   ```js
   const models = await fetch(`${base}/models`).then(r => r.json());
   console.log('Available models:', models.supported_models);
   ```

2. Prepare prompt and/or script using the templates above.

3. Send POST to `/jobs_prompt_tts` with JSON body:
   ```json
   {
     "image_url": "https://.../pet.jpg",
     "prompt": "A friendly golden retriever smiles, blinks, and tilts its head to the right.",
     "text": "Hi, I'm Charlie! Wanna play?",
     "voice_id": "eleven-voice-id",
     "seconds": 6,
     "model": "kwaivgi/kling-v2.1"
   }
   ```

4. Poll server or handle the returned `final_url` when ready (this implementation is synchronous — the endpoint waits for Replicate to finish). In production, consider an async job queue.

## Error handling patterns
- 400: User-provided data (text too long, invalid URL, unsupported model, Replicate/ElevenLabs responded with a job rejection).
- 500: Server config missing (env vars), or third-party token issues.

## Prompt engineering tips
- If lips look off, add "stronger lip sync" or "clear mouth shapes" to the prompt.
- To reduce background artifacts, include "photorealistic" or "realistic pet photo style".
- For character style (cartoon vs photorealistic), be explicit.

## Next steps / improvements
- Switch to an asynchronous job queue and return job ids so the frontend can poll a status endpoint.
- Allow uploading local images directly to Supabase from the client and pass the public URL to the backend.
- Add a small server-side cache for identical requests to save Replicate credits.

## Frontend example (JS)
```js
// assume `base` is the backend base URL
async function createTalkingPet(imageUrl, prompt, text, voiceId, model = null) {
  const res = await fetch(`${base}/jobs_prompt_tts`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      image_url: imageUrl, 
      prompt, 
      text, 
      voice_id: voiceId,
      model  // Will use default if null
    })
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// Get available models
async function getSupportedModels() {
  const res = await fetch(`${base}/models`);
  return res.json();
}
```
