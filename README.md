# InvestingAnalysisAgent

An intelligent agent that continuously monitors company stock information from multiple sources, performs LLM-driven sentiment and impact analysis, and presents findings on a real-time dashboard.

🌐 **Live Demo**: [investassist.online](https://investassist.online/)

## Data Sources
- **SEC EDGAR** — 10-K, 10-Q, 8-K filings
- **Company Official** — Investor relations and news pages
- **Reddit** — r/wallstreetbets, r/stocks, r/investing discussions
- **X/Twitter** — Tweets from high-follower finance accounts

## Quick Start

### Prerequisites
- **Python 3.11+** ([download](https://www.python.org/downloads/))
- Node.js 18+ (for frontend)
- AWS CLI configured (for deployment)

### Local Development

#### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

#### 2. Install dependencies

```bash
# Python backend
pip install -e ".[dev]"

# Frontend
cd src/frontend && npm install
```

#### 3. Configure API Keys

You need **at least one LLM provider key** to run analysis. Gemini is recommended (free tier available).

```bash
cp .env.example .env
```

Then open `.env` and add your keys:

| Provider | How to Get a Key | Free Tier | `.env` Variable |
|----------|-----------------|-----------|-----------------|
| **Google Gemini** ⭐ | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → Click "Create API Key" | ✅ 20 req/day | `GEMINI_API_KEY` |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → "Create new secret key" | ❌ Pay-as-you-go | `OPENAI_API_KEY` |
| **Anthropic** | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) → "Create Key" | ❌ Pay-as-you-go | `ANTHROPIC_API_KEY` |

> **💡 Tip:** Start with just a Gemini key — it's free and sufficient for testing. The system automatically falls back through providers: Gemini → OpenAI → Anthropic.

**Optional** — for Reddit and X/Twitter scrapers:

| Provider | How to Get Credentials | `.env` Variables |
|----------|----------------------|-----------------|
| **Reddit** | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → Create "script" type app | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD` |
| **X / Twitter** | [developer.x.com/en/portal](https://developer.x.com/en/portal/dashboard) → Create project & app | `X_BEARER_TOKEN` |

#### 4. Run locally

```bash
# Start the API server (auto-reloads on changes)
uvicorn src.api.handler:app --reload --port 8000

# In a separate terminal — start the frontend
cd src/frontend && npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

### AWS Deployment

```bash
# Install CDK dependencies
pip install -e ".[cdk]"

# Bootstrap CDK (first time only)
cdk bootstrap

# Deploy all stacks
cd infrastructure && cdk deploy --all
```

## Architecture
- **Compute**: AWS Lambda (serverless, scales to zero)
- **Orchestration**: Step Functions + EventBridge Scheduler (every 3 hours)
- **Storage**: S3 (raw documents) + DynamoDB (analysis results)
- **Frontend**: React + Vite → S3 + CloudFront
- **API**: API Gateway HTTP API + Lambda (FastAPI + Mangum)
- **Notifications**: SNS (email alerts for high-confidence findings)

## Project Structure
```
├── config/                    # Company configuration
├── infrastructure/            # AWS CDK stacks
├── src/
│   ├── scrapers/             # Data collection agents
│   │   ├── sec_agent/        # SEC EDGAR filings
│   │   ├── company_info_agent/ # Official company pages
│   │   ├── reddit_agent/     # Reddit discussions
│   │   └── x_agent/          # X/Twitter posts
│   ├── analyzers/            # LLM analysis pipeline
│   ├── api/                  # Dashboard REST API
│   ├── shared/               # Shared models & utilities
│   └── frontend/             # React dashboard
├── scripts/                  # Dev & testing scripts
└── tests/                    # Unit & integration tests
```

## Cost Estimate (Phase 1 — 30 companies)
- AWS Infrastructure: ~$2/month (free tier covers most services)
- LLM API (Gemini Flash): ~$8-15/month
- **Total: ~$12-18/month**
