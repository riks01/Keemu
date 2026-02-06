# Keemu

**Your intelligent content curator — stay informed without the overwhelm.**

Keemu is a Content Intelligence Assistant that aggregates content from your favorite YouTube channels, Reddit communities, and blogs, then delivers personalized summaries enhanced by AI-powered conversations. Instead of checking dozens of sources manually, let Keemu do the heavy lifting while you focus on what matters.

---

## The Problem

Modern knowledge workers and curious minds face a paradox: more great content exists than ever, but there's never enough time to consume it all. The result? Overflowing "watch later" lists, unread articles, and the nagging feeling of falling behind.

Keemu solves this by becoming your personal content intelligence layer.

---

## What Keemu Does

### 📥 Aggregates Your Sources
Connect your favorite content sources in one place:
- **YouTube Channels** — Track uploads from creators you follow
- **Reddit Communities** — Monitor subreddits and discussions
- **Blogs & Websites** — Follow RSS feeds or let Keemu scrape new articles

### 🧠 Understands Your Content
Keemu doesn't just collect — it comprehends:
- Transcribes video content automatically
- Processes articles and discussions
- Builds a searchable knowledge base unique to you

### 📝 Delivers Smart Summaries
Get periodic digests tailored to your schedule:
- **Cross-source synthesis** — See themes and connections across all your content
- **Source-specific breakdowns** — Drill into what each channel or blog covered
- **Configurable frequency** — Daily, weekly, or custom intervals

### 💬 Chat With Your Content
Powered by RAG (Retrieval-Augmented Generation):
- Ask questions about anything you've followed
- Get answers grounded in your actual content sources
- Explore topics naturally through conversation
- Every response cites its sources

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend                                  │
│         Next.js Web App  •  React Native Mobile Apps            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API Layer                                 │
│                    FastAPI REST API                              │
└─────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐    ┌───────────────────┐    ┌─────────────────┐
│   Collectors  │    │     Processors    │    │   RAG Engine    │
│ YouTube/Reddit│    │ Chunking/Embedding│    │ Vector Search + │
│    /Blogs     │    │                   │    │    Generation   │
└───────────────┘    └───────────────────┘    └─────────────────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Data Layer                                 │
│   PostgreSQL  •  Pinecone (Vectors)  •  Redis  •  S3            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Next.js, React, Tailwind CSS |
| **Mobile** | React Native (iOS & Android) |
| **API** | FastAPI (Python) |
| **Database** | PostgreSQL with pgvector |
| **Vector Store** | Pinecone |
| **Queue/Cache** | Redis + Celery |
| **AI/ML** | OpenAI (GPT-4, Embeddings, TTS, Whisper) |
| **Email** | SendGrid |
| **Storage** | Amazon S3 |
| **Search** | Elasticsearch |

---

## Development Stages

### Stage 1: Backend Foundation
Complete backend infrastructure including authentication (Google OAuth), content collection pipelines, processing engine, RAG system, summary generation, and scheduling — all accessible via REST API.

### Stage 2: Frontend MVP
Full user interface with onboarding, dashboard, source management, chat interface, and settings. A functional product ready for real users.

### Stage 3: Advanced Features
- 🎧 Audio summaries (text-to-speech)
- 📱 Native mobile apps
- 📊 Analytics & insights dashboard
- 🤝 Social features & sharing
- 🎯 Personalization engine
- 💳 Subscription tiers

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Google OAuth** | Secure, passwordless authentication |
| **Multi-source support** | YouTube, Reddit, Blogs/RSS |
| **Automated collection** | Background jobs fetch new content continuously |
| **Smart chunking** | Content is segmented semantically for better retrieval |
| **3-month rolling window** | Recent content stays indexed; older content archived |
| **Timezone-aware scheduling** | Digests arrive when you want them |
| **Source citations** | Every AI response references its sources |
| **Conversation history** | Multi-turn dialogues with context |

---

## Who Is This For?

- **Busy Professionals** — Stay informed in 30 minutes instead of 3 hours
- **Researchers & Students** — Process large volumes of information quickly
- **Lifelong Learners** — Follow multiple interests without feeling overwhelmed

---

## Project Status

🚧 **In Development** — See [PROJECT_STATUS.md](./PROJECT_STATUS.md) for current progress and [GETTING_STARTED.md](./GETTING_STARTED.md) for setup instructions.

---

## Contributing

This is a personal project, but feedback and ideas are welcome! Feel free to open an issue for discussion.

---

## License

MIT License — see [LICENSE](./LICENSE) for details.
