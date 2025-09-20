# Documentation Overview

This repository contains comprehensive documentation for the Talking Pet Backend service. Here's your guide to understanding the codebase and its documentation.

## 📁 Documentation Structure

### Core Documentation Files

| File | Purpose | Audience |
|------|---------|----------|
| **README.md** | Main user documentation, setup, and API reference | All users, quick start |
| **ARCHITECTURE.md** | Technical system architecture and design | Developers, architects |
| **CODE_FLOW.md** | Detailed execution flows and implementation | Developers, debugging |
| **AGENTS.md** | Integration guidelines and prompt templates | Frontend teams, integrators |

### Code Documentation
- **main.py**: Comprehensive inline documentation with detailed docstrings for all functions and endpoints

## 🚀 Quick Start Navigation

### For New Developers
1. Start with **README.md** for overview and setup
2. Read **ARCHITECTURE.md** for system understanding  
3. Dive into **CODE_FLOW.md** for implementation details
4. Reference **main.py** for code-level documentation

### For Frontend Integration
1. **README.md** → API endpoints and examples
2. **AGENTS.md** → Integration patterns and best practices
3. **ARCHITECTURE.md** → Data models and error handling

### For DevOps/Deployment
1. **README.md** → Environment variables and deployment
2. **ARCHITECTURE.md** → Security and scalability considerations
3. **render.yaml** → Production deployment configuration

## 🎯 What This Service Does

The Talking Pet Backend transforms static pet images into animated "talking" videos through AI service orchestration:

```
Static Pet Image + Text Prompt + Speech Text
                    ↓
        [ElevenLabs TTS + Replicate Video + FFmpeg Muxing]
                    ↓
            Talking Pet Video
```

### Key Capabilities
- **Video Animation**: Turn static pet photos into animated videos
- **Speech Synthesis**: Convert text to natural-sounding speech
- **Lip Synchronization**: Combine audio and video with timing adjustments
- **Cloud Storage**: Automatic file management and public URL generation

## 🏗️ System Architecture Overview

```
Frontend → FastAPI Backend → ElevenLabs (Speech)
                           → Replicate (Video)  
                           → Supabase (Storage)
                           → FFmpeg (Muxing)
```

### Technology Stack
- **FastAPI**: Web framework and API layer
- **ElevenLabs**: AI voice synthesis
- **Replicate (Hailuo-02)**: AI video generation
- **Supabase**: Cloud storage and file serving
- **FFmpeg**: Audio/video processing

## 📊 API Summary

| Endpoint | Purpose | Input | Output |
|----------|---------|--------|--------|
| `GET /health` | Health check | None | `{"ok": true}` |
| `POST /jobs_prompt_only` | Video from image + prompt | Image URL + prompt | Video URL |
| `POST /jobs_prompt_tts` | Full talking pet workflow | Image + prompt + text + voice | Audio + Video + Final URLs |
| `POST /debug/head` | URL metadata inspection | URL | Status + content type + size |

## ⚙️ Configuration Quick Reference

### Required Environment Variables
```bash
ELEVEN_API_KEY=         # ElevenLabs API key
REPLICATE_API_TOKEN=    # Replicate API token  
SUPABASE_URL=          # Supabase project URL
SUPABASE_SERVICE_ROLE= # Supabase service role key
```

### Optional Configuration
```bash
SUPABASE_BUCKET=pets        # Storage bucket (default: pets)
ALLOWED_ORIGIN=*            # CORS setting (default: *)
TTS_OUTPUT_FORMAT=mp3_44100_64  # Audio format
TTS_MAX_CHARS=600           # Max input text length
```

## 🔍 Troubleshooting Quick Reference

### Common Issues
- **401/403 from Replicate**: Check `REPLICATE_API_TOKEN`
- **401 from ElevenLabs**: Check `ELEVEN_API_KEY` and voice ID
- **403 from Supabase**: Verify `SUPABASE_SERVICE_ROLE` and bucket exists
- **Audio/video sync issues**: Check duration parameters and muxing settings

### Performance Expectations
- **Prompt-only workflow**: 30-60 seconds
- **Full TTS workflow**: 45-90 seconds
- **File size limits**: Audio <9.5MB, no video limits (handled by providers)

## 🛠️ Development Workflow

### Code Quality Tools
```bash
# Compile check
python -m py_compile main.py

# Linting
flake8 main.py

# Formatting  
black main.py
```

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn main:app --reload

# Access documentation
http://localhost:8000/docs
```

## 📋 Documentation Maintenance

This documentation set is designed to be:
- **Comprehensive**: Covers all aspects from high-level architecture to detailed implementation
- **Layered**: Different levels of detail for different audiences
- **Actionable**: Includes examples, commands, and troubleshooting
- **Current**: Accurately reflects the actual codebase implementation

### When to Update Documentation
- Adding new endpoints or features
- Changing environment variables or configuration
- Modifying third-party service integrations
- Updating deployment procedures
- Fixing issues or adding troubleshooting guidance

---

**Need more specific information?** Each documentation file contains detailed sections for deeper exploration of particular aspects of the system.