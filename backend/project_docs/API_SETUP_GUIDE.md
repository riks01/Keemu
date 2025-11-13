# API Keys & External Services Setup Guide

This guide walks you through setting up all required external services for KeeMU backend.

## Status Checklist
- [x] Anthropic API Key (Already have)
- [x] Google Gemini API Key (Already have)
- [ ] Google OAuth Credentials (for user authentication)
- [ ] YouTube Data API Key
- [ ] Reddit API Credentials
- [ ] SendGrid API Key (for emails)
- [ ] OpenAI API Key (for Whisper transcription - optional, can use local)

---

## 1. Google Cloud Platform Setup

You'll need this for OAuth and YouTube API.

### A. Google OAuth Credentials (for user login)

1. **Go to**: [Google Cloud Console](https://console.cloud.google.com/)
2. **Create a new project** or select existing:
   - Click "Select a project" → "New Project"
   - Name: `KeeMU` or your preferred name
   - Click "Create"

3. **Enable Google+ API**:
   - Go to "APIs & Services" → "Library"
   - Search for "Google+ API"
   - Click "Enable"

4. **Configure OAuth Consent Screen**:
   - Go to "APIs & Services" → "OAuth consent screen"
   - Choose "External" (unless you have Google Workspace)
   - Fill required fields:
     - App name: `KeeMU`
     - User support email: your email
     - Developer contact: your email
   - Click "Save and Continue"
   - Scopes: Add `userinfo.email`, `userinfo.profile`, `openid`
   - Click "Save and Continue"
   - Test users: Add your email for testing
   - Click "Save and Continue"

5. **Create OAuth Credentials**:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: "Web application"
   - Name: `KeeMU Backend`
   - Authorized redirect URIs:
     - `http://localhost:8000/api/v1/auth/google/callback` (for local dev)
     - Add production URL later
   - Click "Create"
   - **SAVE**: Client ID and Client Secret

### B. YouTube Data API Key

1. **Enable YouTube Data API v3**:
   - In same Google Cloud project
   - Go to "APIs & Services" → "Library"
   - Search for "YouTube Data API v3"
   - Click "Enable"

2. **Create API Key**:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "API Key"
   - **SAVE**: API Key
   - (Optional) Click "Restrict Key" → Restrict to "YouTube Data API v3"

---

## 2. Reddit API Setup

1. **Go to**: [Reddit Apps](https://www.reddit.com/prefs/apps)
2. **Login** with your Reddit account (create one if needed)
3. **Scroll to bottom**, click "create another app..."
4. **Fill the form**:
   - Name: `KeeMU Content Aggregator`
   - App type: Select "script"
   - Description: `Content aggregation for personal use`
   - About url: (leave empty or your website)
   - Redirect uri: `http://localhost:8000/api/v1/auth/reddit/callback`
5. **Click "create app"**
6. **SAVE**:
   - Client ID (under the app name, looks like: `xxxxxxxxxxx`)
   - Client Secret (labeled as "secret")
   - Your Reddit username
   - Your Reddit password (for PRAW authentication)

---

## 3. SendGrid Setup (Email Notifications)

1. **Go to**: [SendGrid Signup](https://signup.sendgrid.com/)
2. **Create free account**:
   - Free tier: 100 emails/day (sufficient for development)
   - Fill registration details
   - Verify email address

3. **Create API Key**:
   - Login to SendGrid
   - Go to "Settings" → "API Keys"
   - Click "Create API Key"
   - Name: `KeeMU Backend`
   - Permissions: "Full Access" (or "Restricted Access" with Mail Send enabled)
   - Click "Create & View"
   - **SAVE**: API Key (shown only once!)

4. **Verify Sender Identity** (required for sending emails):
   - Go to "Settings" → "Sender Authentication"
   - Choose "Single Sender Verification" (easier for dev)
   - Fill form with your email
   - Verify email address
   - This email will be the "From" address in notifications

---

## 4. OpenAI API (Optional - for Whisper transcription)

**Note**: We'll use this only as fallback. Most YouTube videos have transcripts.

1. **Go to**: [OpenAI API](https://platform.openai.com/)
2. **Sign up** or login
3. **Add payment method** (required for API access):
   - Go to "Settings" → "Billing"
   - Add credit card
   - Set usage limits (recommend $10-20/month for testing)

4. **Create API Key**:
   - Go to "API Keys"
   - Click "Create new secret key"
   - Name: `KeeMU Backend`
   - **SAVE**: API Key (shown only once!)

**Cost Estimate**: 
- Whisper API: ~$0.006 per minute of audio
- For a 10-min video without transcript: ~$0.06
- We'll minimize usage by preferring existing transcripts

---

## 5. Vector Database Options

You have two options. Start with **Option A** (free, simpler):

### Option A: PostgreSQL with pgvector (Recommended to start)

**No setup needed** - we'll configure this in Docker.

**Pros**: 
- Free, runs locally
- Good for development and small-to-medium scale
- Easier to debug and manage

**Cons**: 
- Slower than specialized vector DBs at very large scale
- Requires more manual optimization

### Option B: Pinecone (Optional, for production scale)

1. **Go to**: [Pinecone](https://www.pinecone.io/)
2. **Sign up** for free tier:
   - Free tier: 1 index, 100K vectors (good for testing)
3. **Create API Key**:
   - Go to "API Keys"
   - Copy your API key
   - Note your environment (e.g., `us-west1-gcp`)
4. **SAVE**: API Key and Environment

**Recommendation**: Start with pgvector, add Pinecone later if needed.

---

## 6. Environment Variables Template

Once you have all keys, you'll store them in `.env` file. Here's the template:

```bash
# Application
APP_ENV=development
DEBUG=true
SECRET_KEY=your-secret-key-generate-random-string

# Database
DATABASE_URL=postgresql://keemu_user:keemu_password@postgres:5432/keemu_db

# Redis
REDIS_URL=redis://redis:6379/0

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback

# YouTube API
YOUTUBE_API_KEY=your-youtube-api-key

# Reddit API
REDDIT_CLIENT_ID=your-reddit-client-id
REDDIT_CLIENT_SECRET=your-reddit-client-secret
REDDIT_USER_AGENT=KeeMU/1.0

# Anthropic
ANTHROPIC_API_KEY=your-anthropic-api-key

# Google Gemini (if we use it)
GEMINI_API_KEY=your-gemini-api-key

# OpenAI (optional, for Whisper fallback)
OPENAI_API_KEY=your-openai-api-key

# SendGrid
SENDGRID_API_KEY=your-sendgrid-api-key
SENDGRID_FROM_EMAIL=your-verified-sender-email@example.com

# Vector Database
VECTOR_DB_TYPE=pgvector  # or 'pinecone'
# If using Pinecone:
# PINECONE_API_KEY=your-pinecone-api-key
# PINECONE_ENVIRONMENT=us-west1-gcp

# Model Configuration
EMBEDDING_MODEL=google/embeddinggemma-300m
LLM_MODEL=claude-3-5-haiku-20241022
EMBEDDING_DIMENSION=768  # for embeddinggemma-300m

# Cost/Performance Toggles
USE_LOCAL_WHISPER=false  # true = use local Whisper (slower, free), false = use OpenAI API
BATCH_SIZE_EMBEDDINGS=32
BATCH_SIZE_COLLECTION=50
```

---

## Setup Priority

**Essential for basic functionality:**
1. ✅ Anthropic API (you have)
2. ✅ Google OAuth Credentials (needed for user login)
3. ✅ YouTube API Key (for YouTube content collection)

**Important but can mock initially:**
4. Reddit API (can mock with sample data)
5. SendGrid (can log emails to console instead)

**Optional/Later:**
6. OpenAI API (only for videos without transcripts)
7. Pinecone (only if pgvector isn't sufficient)

---

## Next Steps

1. **Start with essentials**: Get Google OAuth and YouTube API first
2. **Save all keys securely**: Use a password manager
3. **Never commit `.env` file**: We'll add it to `.gitignore`
4. **Test each API**: We'll build health check endpoints

Let me know when you have at least the Google OAuth and YouTube API keys, and we can start building! 🚀
