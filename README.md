# InvestingAnalysisAgent

An intelligent agent that continuously monitors company stock information from multiple sources, performs LLM-driven sentiment and impact analysis, and presents findings on a real-time dashboard.

## Data Sources
- **SEC EDGAR** — 10-K, 10-Q, 8-K filings
- **Company Official** — Investor relations and news pages
- **Reddit** — r/wallstreetbets, r/stocks, r/investing discussions
- **X/Twitter** — Tweets from high-follower finance accounts

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+ (for frontend)
- AWS CLI configured (for deployment)

### Local Development

```bash
# Install Python dependencies
pip install -e ".[dev]"

# Copy and fill in API keys
cp .env.example .env

# Run the pipeline locally for testing
python scripts/local_run.py

# Start the frontend dev server
cd src/frontend && npm install && npm run dev
```

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
