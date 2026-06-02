#!/usr/bin/env bash
# ============================================================
# InvestingAssistant — First-Time AWS Setup
# ============================================================
# Run this script ONCE on a fresh AWS account before deploying.
#
# Prerequisites:
#   - AWS CLI installed and configured (aws configure)
#   - Node.js 20+ and npm installed
#   - Python 3.12+ installed
#
# Usage:
#   chmod +x scripts/bootstrap_aws.sh
#   ./scripts/bootstrap_aws.sh
# ============================================================

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"

echo "========================================"
echo " InvestingAssistant — AWS Bootstrap"
echo "========================================"
echo ""

# 1. Check AWS credentials
echo "[1/5] Checking AWS credentials..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
if [ -z "$ACCOUNT_ID" ]; then
    echo "ERROR: AWS credentials not configured. Run 'aws configure' first."
    exit 1
fi
echo "  ✓ Account: $ACCOUNT_ID"
echo "  ✓ Region:  $REGION"
echo ""

# 2. Install CDK
echo "[2/5] Installing AWS CDK..."
npm install -g aws-cdk 2>/dev/null || true
echo "  ✓ CDK version: $(cdk --version)"
echo ""

# 3. CDK Bootstrap
echo "[3/5] Bootstrapping CDK in $REGION..."
cdk bootstrap aws://$ACCOUNT_ID/$REGION
echo "  ✓ CDK bootstrapped"
echo ""

# 4. Create Secrets Manager entries
echo "[4/5] Creating Secrets Manager entries..."
echo "  (You'll need to update these with real values later)"

aws secretsmanager create-secret \
    --name "investing-assistant/reddit" \
    --description "Reddit API credentials" \
    --secret-string '{"client_id":"","client_secret":"","username":"","password":""}' \
    --region $REGION 2>/dev/null || echo "  → Reddit secret already exists (skipping)"

aws secretsmanager create-secret \
    --name "investing-assistant/x-api" \
    --description "X/Twitter API Bearer Token" \
    --secret-string '{"bearer_token":""}' \
    --region $REGION 2>/dev/null || echo "  → X API secret already exists (skipping)"

aws secretsmanager create-secret \
    --name "investing-assistant/llm-keys" \
    --description "LLM API keys" \
    --secret-string '{"gemini_api_key":"","openai_api_key":"","anthropic_api_key":""}' \
    --region $REGION 2>/dev/null || echo "  → LLM keys secret already exists (skipping)"

echo "  ✓ Secrets created (update them with real keys via AWS Console)"
echo ""

# 5. Print GitHub setup instructions
echo "[5/5] GitHub Actions Setup"
echo "========================================"
echo ""
echo "Add these secrets to your GitHub repo:"
echo "  Settings → Secrets and variables → Actions → New repository secret"
echo ""
echo "  AWS_ACCOUNT_ID     = $ACCOUNT_ID"
echo "  AWS_ACCESS_KEY_ID  = (your IAM access key)"
echo "  AWS_SECRET_ACCESS_KEY = (your IAM secret key)"
echo "  JWT_SECRET         = (generate with: openssl rand -hex 32)"
echo "  ADMIN_USERNAME     = (your admin username)"
echo "  ADMIN_PASSWORD     = (a strong password)"
echo "  VITE_GOOGLE_CLIENT_ID = (Google OAuth client ID, optional)"
echo ""
echo "========================================"
echo " Bootstrap complete!"
echo " Next: push to 'main' branch to trigger deployment"
echo "========================================"
