#!/usr/bin/env python3
"""
AWS CDK app entry point for InvestingAssistant.

Deploys four stacks in dependency order:
  1. StorageStack   — S3 + DynamoDB (stateful, RETAIN)
  2. PipelineStack  — Lambdas + Step Functions + EventBridge
  3. ApiStack       — API Gateway + API Lambda
  4. FrontendStack  — S3 + CloudFront
"""

import os
import aws_cdk as cdk

from stacks.storage_stack import StorageStack
from stacks.pipeline_stack import PipelineStack
from stacks.api_stack import ApiStack
from stacks.frontend_stack import FrontendStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=app.node.try_get_context("region") or "us-east-1",
)

# Tags applied to all resources
tags = {
    "Project": "InvestingAssistant",
    "Environment": "dev",
    "ManagedBy": "CDK",
}

# 1. Stateful resources — separate stack to prevent accidental deletion
storage = StorageStack(app, "InvestingAssistant-Storage", env=env)

# 2. Pipeline — scrapers, analyzers, orchestration (runs every 12 hours)
pipeline = PipelineStack(
    app,
    "InvestingAssistant-Pipeline",
    raw_bucket=storage.raw_bucket,
    analysis_table=storage.analysis_table,
    processed_docs_table=storage.processed_docs_table,
    job_runs_table=storage.job_runs_table,
    env=env,
)
pipeline.add_dependency(storage)

# 3. API backend
api = ApiStack(
    app,
    "InvestingAssistant-Api",
    analysis_table=storage.analysis_table,
    processed_docs_table=storage.processed_docs_table,
    job_runs_table=storage.job_runs_table,
    raw_bucket=storage.raw_bucket,
    env=env,
)
api.add_dependency(storage)

# 4. Frontend hosting
frontend = FrontendStack(
    app,
    "InvestingAssistant-Frontend",
    api_url=api.api_url,
    env=env,
)
frontend.add_dependency(api)

# Apply tags to all stacks
for key, value in tags.items():
    cdk.Tags.of(app).add(key, value)

app.synth()
