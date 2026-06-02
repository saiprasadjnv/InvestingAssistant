"""
Configuration loader for the InvestingAnalysisAgent.

Loads company list from JSON config, environment variables,
and API keys from AWS Secrets Manager (prod) or .env (local).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .models import Company


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
COMPANIES_CONFIG_PATH = CONFIG_DIR / "companies_interested.json"


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def get_environment() -> str:
    """Return current environment: 'local', 'dev', or 'prod'."""
    return os.environ.get("INVESTING_ASSISTANT_ENV", "local")


def is_local() -> bool:
    return get_environment() == "local"


def is_aws() -> bool:
    return get_environment() in ("dev", "prod")


# ---------------------------------------------------------------------------
# Company Configuration
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_companies(config_path: Optional[str] = None) -> list[Company]:
    """
    Load the list of companies to track from the JSON config file.

    Args:
        config_path: Override path to the config file. Defaults to
                     config/companies_interested.json.

    Returns:
        List of Company model instances.
    """
    path = Path(config_path) if config_path else COMPANIES_CONFIG_PATH

    if not path.exists():
        raise FileNotFoundError(
            f"Companies config not found at {path}. "
            f"Expected a JSON file with an 'interested_companies' array."
        )

    with open(path, "r") as f:
        data = json.load(f)

    companies = []
    for entry in data.get("interested_companies", []):
        companies.append(
            Company(
                name=entry["name"],
                ticker=entry["ticker"],
                sector=entry.get("sector", "Unknown"),
                cik=entry.get("CIK", ""),
                investor_page_url=entry.get("investor_page_url"),
                news_page_url=entry.get("news_page_url"),
            )
        )

    return companies


def get_company_by_ticker(ticker: str) -> Optional[Company]:
    """Look up a company by ticker symbol."""
    for company in load_companies():
        if company.ticker.upper() == ticker.upper():
            return company
    return None


def reload_companies() -> list[Company]:
    """Clear the lru_cache and re-read companies from disk."""
    load_companies.cache_clear()
    return load_companies()


def add_company(company_data: dict) -> Company:
    """
    Add a new company to the JSON config and return the Company model.

    Args:
        company_data: Dict with keys matching the Company model fields
                      (name, ticker, sector, cik, investor_page_url, news_page_url).

    Returns:
        The newly created Company instance.

    Raises:
        ValueError: If a company with the same ticker already exists.
    """
    with open(COMPANIES_CONFIG_PATH, "r") as f:
        data = json.load(f)

    existing_tickers = {
        entry["ticker"].upper()
        for entry in data.get("interested_companies", [])
    }
    if company_data.get("ticker", "").upper() in existing_tickers:
        raise ValueError(
            f"Company with ticker '{company_data['ticker']}' already exists."
        )

    new_entry = {
        "name": company_data["name"],
        "ticker": company_data["ticker"],
        "sector": company_data.get("sector", "Unknown"),
        "CIK": company_data.get("cik", ""),
        "investor_page_url": company_data.get("investor_page_url"),
        "news_page_url": company_data.get("news_page_url"),
    }

    data.setdefault("interested_companies", []).append(new_entry)

    with open(COMPANIES_CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4)

    reload_companies()

    return Company(
        name=new_entry["name"],
        ticker=new_entry["ticker"],
        sector=new_entry["sector"],
        cik=new_entry["CIK"],
        investor_page_url=new_entry.get("investor_page_url"),
        news_page_url=new_entry.get("news_page_url"),
    )


def remove_company(ticker: str) -> bool:
    """
    Remove a company from the JSON config by ticker symbol.

    Args:
        ticker: The ticker symbol to remove (case-insensitive).

    Returns:
        True if the company was successfully removed.

    Raises:
        ValueError: If no company with the given ticker exists.
    """
    with open(COMPANIES_CONFIG_PATH, "r") as f:
        data = json.load(f)

    original = data.get("interested_companies", [])
    filtered = [
        entry for entry in original
        if entry["ticker"].upper() != ticker.upper()
    ]

    if len(filtered) == len(original):
        raise ValueError(f"No company found with ticker '{ticker}'.")

    data["interested_companies"] = filtered

    with open(COMPANIES_CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4)

    reload_companies()
    return True


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------

class APIKeys:
    """
    Retrieves API keys from environment variables (local) or
    AWS Secrets Manager (deployed).
    """

    @staticmethod
    def _get_secret(secret_name: str) -> dict:
        """Fetch a secret from AWS Secrets Manager."""
        import boto3
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])

    @staticmethod
    def _get_env_or_secret(env_key: str, secret_name: str, secret_field: str) -> str:
        """Get value from env var (local) or Secrets Manager (AWS)."""
        # Try environment variable first
        value = os.environ.get(env_key)
        if value:
            return value

        # Fall back to Secrets Manager if on AWS
        if is_aws():
            try:
                secrets = APIKeys._get_secret(secret_name)
                return secrets.get(secret_field, "")
            except Exception as e:
                raise RuntimeError(
                    f"Failed to retrieve secret '{secret_name}.{secret_field}': {e}"
                )

        raise ValueError(
            f"API key not found. Set {env_key} environment variable "
            f"or configure Secrets Manager secret '{secret_name}'."
        )

    # Reddit (PRAW)
    @staticmethod
    def reddit_client_id() -> str:
        return APIKeys._get_env_or_secret(
            "REDDIT_CLIENT_ID", "investing-assistant/reddit", "client_id"
        )

    @staticmethod
    def reddit_client_secret() -> str:
        return APIKeys._get_env_or_secret(
            "REDDIT_CLIENT_SECRET", "investing-assistant/reddit", "client_secret"
        )

    @staticmethod
    def reddit_username() -> str:
        return APIKeys._get_env_or_secret(
            "REDDIT_USERNAME", "investing-assistant/reddit", "username"
        )

    @staticmethod
    def reddit_password() -> str:
        return APIKeys._get_env_or_secret(
            "REDDIT_PASSWORD", "investing-assistant/reddit", "password"
        )

    # X / Twitter
    @staticmethod
    def x_bearer_token() -> str:
        return APIKeys._get_env_or_secret(
            "X_BEARER_TOKEN", "investing-assistant/x-api", "bearer_token"
        )

    # LLM Providers
    @staticmethod
    def gemini_api_key() -> str:
        return APIKeys._get_env_or_secret(
            "GEMINI_API_KEY", "investing-assistant/llm-keys", "gemini_api_key"
        )

    @staticmethod
    def openai_api_key() -> str:
        return APIKeys._get_env_or_secret(
            "OPENAI_API_KEY", "investing-assistant/llm-keys", "openai_api_key"
        )

    @staticmethod
    def anthropic_api_key() -> str:
        return APIKeys._get_env_or_secret(
            "ANTHROPIC_API_KEY", "investing-assistant/llm-keys", "anthropic_api_key"
        )


# ---------------------------------------------------------------------------
# AWS Resource Configuration
# ---------------------------------------------------------------------------

def get_s3_bucket_name() -> str:
    """Return the S3 bucket name for raw document storage."""
    return os.environ.get("S3_RAW_BUCKET", "investingassistant-raw-local")


def get_dynamodb_table_name(table_key: str) -> str:
    """
    Return the DynamoDB table name, respecting environment prefix.

    Args:
        table_key: One of 'analysis', 'processed_docs', 'job_runs'
    """
    env = get_environment()
    prefix = f"{env}-" if env != "prod" else ""

    table_map = {
        "analysis": f"{prefix}InvestingAssistant-AnalysisResults",
        "processed_docs": f"{prefix}InvestingAssistant-ProcessedDocuments",
        "job_runs": f"{prefix}InvestingAssistant-JobRuns",
    }

    if table_key not in table_map:
        raise ValueError(f"Unknown table key: {table_key}. Valid: {list(table_map.keys())}")

    return table_map[table_key]
