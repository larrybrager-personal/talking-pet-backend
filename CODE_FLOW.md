# Code Flow Documentation

This document explains the detailed execution flow of the Talking Pet Backend API endpoints.

## Endpoint: `GET /health`

**Purpose**: Simple health check for deployment monitoring.

**Flow**:
```
1. Receive GET request to /health
2. Return {"ok": True}
```

**Duration**: <1ms  
**Dependencies**: None

---

## Endpoint: `POST /jobs_prompt_only`

**Purpose**: Generate animated video from static image and text prompt.

**Input**: `JobPromptOnly` model
```json
{
  "image_url": "https://example.com/pet.jpg",
  "prompt": "The dog tilts its head and smiles",
  "seconds": 6,
  "resolution": "768p",
  "model": "minimax/hailuo-02"
}
```

**Execution Flow**:
```
1. Validate request body using Pydantic model
2. Call hailuo_video_from_prompt() with parameters
   └── Delegates to replicate_video_from_prompt()
       ├── Validate REPLICATE_API_TOKEN exists
       ├── Construct payload for Replicate API
       ├── POST to https://api.replicate.com/v1/models/{model}/predictions
       ├── Extract prediction ID from response
       └── Poll prediction status every 2 seconds until completion
           ├── GET https://api.replicate.com/v1/predictions/{id}
           ├── Check status: "succeeded", "failed", or "canceled"
           ├── On success: extract video URL from output
           └── On failure: raise HTTPException with error details
3. Return {"video_url": "https://..."}
```

**Duration**: 30-60 seconds (mostly Replicate processing time)  
**Dependencies**: Replicate API

**Error Scenarios**:
- Missing `REPLICATE_API_TOKEN` → 500 error
- Invalid image URL → 400 error from Replicate
- Replicate job failure → 400 error with provider details

---

## Endpoint: `POST /jobs_prompt_tts`

**Purpose**: Generate video with synchronized speech (full talking pet workflow).

**Input**: `JobPromptTTS` model
```json
{
  "image_url": "https://example.com/pet.jpg", 
  "prompt": "The dog opens its mouth and speaks happily",
  "text": "Hello! How are you today?",
  "voice_id": "21m00Tcm4TlvDq8ikWAM",
  "seconds": 6,
  "resolution": "768p"
}
```

**Execution Flow**:
```
1. Validate request body using Pydantic model

2. STEP 1: Synthesize speech with ElevenLabs
   └── Call elevenlabs_tts_bytes(req.text, req.voice_id)
       ├── Validate ELEVEN_API_KEY exists
       ├── Check text length ≤ TTS_MAX_CHARS (default 600)
       ├── POST to https://api.elevenlabs.io/v1/text-to-speech/{voice_id}
       │   └── Payload: {text, model_id: "eleven_multilingual_v2", output_format}
       ├── Validate response audio size ≤ 9.5MB
       └── Return raw MP3 bytes

3. STEP 2: Upload audio to Supabase Storage
   └── Call supabase_upload(mp3_bytes, "audio/{uuid}.mp3", "audio/mpeg")
       ├── Validate SUPABASE_URL and SUPABASE_SERVICE_ROLE exist
       ├── Construct upload URL: {SUPABASE_URL}/storage/v1/object/{bucket}/{path}
       ├── POST with service role authentication and upsert=true
       └── Return public URL: {SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}?download=1

4. STEP 3: Generate video with Replicate
   └── Call hailuo_video_from_prompt() (same as jobs_prompt_only)
       └── Returns video URL from Replicate

5. STEP 4: Combine audio and video
   └── Call mux_video_audio(video_url, audio_public_url)
       ├── Create temporary directory
       ├── Download video from Replicate URL to temp file
       ├── Download audio from Supabase URL to temp file
       ├── Execute FFmpeg with imageio-ffmpeg:
       │   └── Command: ffmpeg -y -i video.mp4 -i audio.mp3 -c:v copy -c:a aac 
       │       -af "adelay=500|500" -shortest output.mp4
       │       ├── -c:v copy: Don't re-encode video (faster)
       │       ├── -c:a aac: Encode audio to AAC for compatibility
       │       ├── -af "adelay=500|500": Add 0.5s delay to audio for lip-sync
       │       └── -shortest: Match duration of shortest stream
       ├── Read final MP4 bytes
       └── Clean up temporary directory

6. STEP 5: Upload final video to Supabase
   └── Call supabase_upload(final_bytes, "videos/{uuid}.mp4", "video/mp4")

7. Return response with all URLs:
   {
     "audio_url": "https://.../audio/{uuid}.mp3",
     "video_url": "https://...replicate.delivery/video.mp4", 
     "final_url": "https://.../videos/{uuid}.mp4"
   }
```

**Duration**: 45-90 seconds total
- ElevenLabs TTS: 5-15 seconds
- Replicate video: 30-60 seconds  
- Audio/video download: 5-10 seconds
- FFmpeg muxing: 2-5 seconds
- Supabase uploads: 2-10 seconds

**Dependencies**: ElevenLabs API, Replicate API, Supabase Storage, FFmpeg

**Error Scenarios**:
- Missing API keys → 500 error
- Text too long (>600 chars) → 400 error
- Audio too large (>9.5MB) → 400 error
- ElevenLabs API failure → 400 error with provider details
- Replicate failure → 400 error with provider details
- Supabase upload failure → HTTP status from provider
- FFmpeg failure → Exception (usually file corruption)

---

## Endpoint: `POST /debug/head`

**Purpose**: Debugging utility for inspecting remote URL metadata.

**Input**: `HeadRequest` model
```json
{"url": "https://example.com/image.jpg"}
```

**Execution Flow**:
```
1. Validate request body
2. Call head_info(url)
   ├── Try HEAD request to URL with 30s timeout
   ├── If HEAD fails (4xx): fallback to GET with Range: bytes=0-1 
   ├── Extract: status_code, content-type header, content-length header
   └── Return tuple (status, content_type, size)
3. Return JSON response: {"status": 200, "content_type": "image/jpeg", "bytes": 12345}
```

**Duration**: 1-5 seconds  
**Dependencies**: Remote URL accessibility

**Use Cases**:
- Validate image URLs before sending to Replicate
- Check file sizes for optimization
- Debug remote resource issues

---

## Key Helper Functions

### `supabase_upload(file_bytes, object_path, content_type)`
- Authenticates with Supabase service role key
- Uses upsert=true to overwrite existing files
- Returns public URL with ?download=1 for proper content-type headers
- Handles errors with HTTP status codes from Supabase

### `replicate_video_from_prompt(model, image_url, prompt, seconds, resolution)`
- Creates prediction job with Replicate
- Polls every 2 seconds until completion (can take 30-60 seconds)
- Handles both list and string output formats from different models
- Synchronous implementation (blocks until complete)

### `mux_video_audio(video_url, audio_url)`
- Downloads both files to temporary storage
- Uses imageio-ffmpeg for cross-platform FFmpeg support
- Adds 0.5s audio delay for better lip synchronization
- Cleans up temporary files automatically
- Returns final video as raw bytes

## Configuration Impact on Flow

### Environment Variables Effect on Execution:
- `TTS_MAX_CHARS`: Limits input text length validation
- `TTS_OUTPUT_FORMAT`: Changes ElevenLabs output format
- `SUPABASE_BUCKET`: Changes storage path for uploads
- `ALLOWED_ORIGIN`: Affects CORS headers (not execution flow)

### Performance Tuning Options:
- Reduce `TTS_OUTPUT_FORMAT` bitrate for faster uploads
- Adjust timeout values in HTTP clients for different network conditions
- Consider async job queue for production to avoid request timeouts

## Error Handling Strategy

### HTTP Status Code Mapping:
- **200**: Successful completion
- **400**: Client error (invalid input, provider rejection, validation failure)
- **500**: Server error (missing config, unexpected provider errors)

### Provider Error Forwarding:
- ElevenLabs errors → 400 with provider message
- Replicate errors → 400 with provider logs and error details  
- Supabase errors → Original HTTP status with provider message

### Validation Layers:
1. **Pydantic models**: Basic type and required field validation
2. **Business logic**: Text length, file size, API key presence
3. **Provider APIs**: URL validity, voice ID existence, model availability