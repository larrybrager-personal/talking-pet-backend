# Architecture Documentation

## Overview
The Talking Pet Backend is a FastAPI-based microservice that orchestrates multiple third-party APIs to transform static pet images into animated "talking" videos. The service provides two main workflows: prompt-only animation generation and prompt + text-to-speech (TTS) synthesis.

## System Architecture

```
┌─────────────┐    ┌───────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Client    │───▶│  FastAPI      │───▶│   ElevenLabs    │    │    Replicate    │
│ (Frontend)  │    │   Backend     │    │      TTS        │    │   (Hailuo-02)   │
└─────────────┘    └───────────────┘    └─────────────────┘    └─────────────────┘
                           │                        │                     │
                           ▼                        ▼                     ▼
                   ┌───────────────┐    ┌─────────────────┐    ┌─────────────────┐
                   │   Supabase    │    │     Audio       │    │     Video       │
                   │   Storage     │    │   (MP3 files)   │    │   (MP4 files)   │
                   └───────────────┘    └─────────────────┘    └─────────────────┘
                           │                        │                     │
                           └────────────────────────┼─────────────────────┘
                                                    ▼
                                            ┌───────────────┐
                                            │    FFmpeg     │
                                            │   (Muxing)    │
                                            └───────────────┘
```

## Core Components

### 1. FastAPI Application (`main.py`)
- **Purpose**: HTTP API server and orchestration layer
- **Responsibilities**:
  - Request validation using Pydantic models
  - CORS handling for frontend integration
  - API endpoint routing
  - Error handling and HTTP status codes
  - Coordination of third-party service calls

### 2. Third-Party Service Integrations

#### ElevenLabs TTS Integration
- **Function**: `elevenlabs_tts_bytes()`
- **Purpose**: Convert text to speech using AI voice synthesis
- **Input**: Text string + voice_id
- **Output**: Raw MP3 audio bytes
- **Constraints**: 
  - Maximum text length: 600 characters (configurable via `TTS_MAX_CHARS`)
  - Maximum output size: 9.5MB
- **Model**: `eleven_multilingual_v2`

#### Replicate/Hailuo-02 Integration
- **Functions**: `replicate_video_from_prompt()`, `hailuo_video_from_prompt()`
- **Purpose**: Generate animated videos from static images and text prompts
- **Input**: Image URL + animation prompt + duration + resolution
- **Output**: MP4 video URL
- **Features**:
  - Synchronous polling for job completion
  - Support for custom models (defaults to `minimax/hailuo-02`)
  - Configurable duration (default: 6 seconds)
  - Configurable resolution (default: 768p)

#### Supabase Storage Integration
- **Function**: `supabase_upload()`
- **Purpose**: Store and serve generated media files
- **Features**:
  - Public URL generation for client access
  - Automatic file versioning with UUID-based naming
  - Support for multiple content types (audio/mpeg, video/mp4)
  - Organized folder structure (audio/, videos/)

### 3. Media Processing

#### FFmpeg Audio/Video Muxing
- **Function**: `mux_video_audio()`
- **Purpose**: Combine generated video with synthesized audio
- **Implementation**: Uses `imageio-ffmpeg` for cross-platform compatibility
- **Features**:
  - Audio delay compensation (0.5s) for better lip-sync
  - `-shortest` flag to match duration of shortest stream
  - Temporary file management with automatic cleanup
  - AAC audio encoding for broad compatibility

## API Endpoints

### Core Endpoints

#### `GET /health`
- **Purpose**: Service health check
- **Response**: `{"ok": true}`
- **Use Case**: Load balancer health checks, deployment verification

#### `POST /jobs_prompt_only`
- **Purpose**: Generate video from image + prompt only
- **Input**: `JobPromptOnly` model
- **Process Flow**:
  1. Validate request parameters
  2. Call Replicate API for video generation
  3. Return video URL directly (no audio synthesis or muxing)

#### `POST /jobs_prompt_tts`
- **Purpose**: Generate video with synchronized speech
- **Input**: `JobPromptTTS` model
- **Process Flow**:
  1. Synthesize speech using ElevenLabs TTS
  2. Upload audio to Supabase Storage
  3. Generate video using Replicate
  4. Download both audio and video
  5. Mux audio and video using FFmpeg
  6. Upload final video to Supabase Storage
  7. Return URLs for audio, video, and final muxed file

#### `POST /debug/head`
- **Purpose**: Debugging utility for URL metadata
- **Input**: `HeadRequest` model with URL
- **Output**: HTTP status, content type, and file size

## Data Models

### Request Models (Pydantic)

```python
class JobPromptOnly(BaseModel):
    image_url: str          # Public URL to pet image
    prompt: str             # Animation description
    seconds: int = 6        # Video duration
    resolution: str = "768p" # Output resolution
    model: str | None = None # Replicate model override

class JobPromptTTS(BaseModel):
    # Inherits all JobPromptOnly fields, plus:
    text: str               # Script for TTS
    voice_id: str           # ElevenLabs voice identifier

class HeadRequest(BaseModel):
    url: str                # URL to inspect
```

## Configuration

### Environment Variables
```bash
# Required
ELEVEN_API_KEY=          # ElevenLabs API key
REPLICATE_API_TOKEN=     # Replicate API token
SUPABASE_URL=            # Supabase project URL
SUPABASE_SERVICE_ROLE=   # Supabase service role key

# Optional with defaults
SUPABASE_BUCKET=pets     # Storage bucket name
ALLOWED_ORIGIN=*         # CORS origin setting
TTS_OUTPUT_FORMAT=mp3_44100_64  # ElevenLabs output format
TTS_MAX_CHARS=600        # Maximum TTS input length
```

## Security Considerations

### Authentication & Authorization
- **Supabase**: Uses service role key for backend-to-storage authentication
- **ElevenLabs**: API key-based authentication
- **Replicate**: Token-based authentication
- **No user authentication**: Service assumes authentication handled upstream

### Data Privacy
- **Temporary Files**: All temporary media files are cleaned up after processing
- **No Persistence**: Service doesn't store user data beyond media files in Supabase
- **Public URLs**: Generated content is publicly accessible via Supabase URLs

### CORS Configuration
- **Development**: Defaults to allow all origins (`*`)
- **Production**: Should be configured to specific frontend domain

## Error Handling

### HTTP Status Codes
- **200**: Successful operation
- **400**: Client error (invalid input, text too long, provider rejection)
- **500**: Server error (missing configuration, provider API errors)

### Error Categories
1. **Configuration Errors**: Missing environment variables
2. **Validation Errors**: Invalid request parameters
3. **Provider Errors**: Third-party API failures
4. **Resource Errors**: File size limits, storage issues

## Performance Characteristics

### Latency
- **Prompt-only workflow**: ~30-60 seconds (Replicate generation time)
- **TTS workflow**: ~45-90 seconds (TTS + video generation + muxing)
- **File operations**: Minimal overhead with async I/O

### Scalability
- **Stateless**: No server-side session storage
- **Async**: Non-blocking I/O for external API calls
- **Resource limits**: Bounded by third-party API rate limits

### Resource Usage
- **Memory**: Temporary storage of media files during muxing
- **CPU**: FFmpeg processing for audio/video combination
- **Storage**: Managed by Supabase (external)

## Deployment

### Platform Support
- **Primary**: Render.com (via `render.yaml`)
- **Alternative**: Any platform supporting Python/FastAPI
- **Requirements**: Python 3.10+, no system dependencies

### Scaling Considerations
- **Horizontal**: Stateless design supports multiple instances
- **Provider Limits**: Rate limiting from ElevenLabs/Replicate may require queuing
- **Storage**: Supabase provides managed scaling for file storage

## Future Enhancements

### Potential Improvements
1. **Async Job Queue**: Replace synchronous processing with job queue system
2. **Caching**: Cache identical requests to reduce provider costs
3. **Batch Processing**: Support multiple pet images in single request
4. **Webhook Support**: Notify clients when long-running jobs complete
5. **Audio Format Options**: Support multiple output formats beyond MP3
6. **Custom Model Support**: Easy integration of new animation models