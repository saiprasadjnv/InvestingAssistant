"""
Pipeline Stack — Scraper Lambdas, Analyzer Lambdas, Step Functions, EventBridge.

Orchestrates the data collection and analysis pipeline that runs every 12 hours.
"""

from pathlib import Path
from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as sfn_tasks,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
)

# Path to the project root for Lambda packaging
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


class PipelineStack(Stack):
    """Serverless pipeline: scrapers → analyzers → storage → alerts."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        raw_bucket: s3.IBucket,
        analysis_table: dynamodb.ITable,
        processed_docs_table: dynamodb.ITable,
        job_runs_table: dynamodb.ITable,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # Lambda Layer — Python dependencies (built in CI/CD)
        # ---------------------------------------------------------------
        layer_path = str(Path(PROJECT_ROOT) / "build" / "lambda-layer")
        self._deps_layer = _lambda.LayerVersion(
            self, "PythonDepsLayer",
            code=_lambda.Code.from_asset(layer_path),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            description="Python dependencies for InvestingAssistant Lambdas",
        )

        # ---------------------------------------------------------------
        # Secrets Manager — reference existing secrets (created by bootstrap)
        # ---------------------------------------------------------------
        reddit_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "RedditSecret", "investing-assistant/reddit",
        )

        x_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "XApiSecret", "investing-assistant/x-api",
        )

        llm_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "LLMKeysSecret", "investing-assistant/llm-keys",
        )

        # ---------------------------------------------------------------
        # SNS Topic — High-confidence alerts
        # ---------------------------------------------------------------
        self.alert_topic = sns.Topic(
            self, "AlertTopic",
            topic_name="investing-assistant-alerts",
            display_name="InvestingAssistant High-Confidence Alerts",
        )

        # Common environment variables for all Lambdas
        common_env = {
            "INVESTING_ASSISTANT_ENV": "dev",
            "S3_RAW_BUCKET": raw_bucket.bucket_name,
            "ANALYSIS_TABLE": analysis_table.table_name,
            "PROCESSED_DOCS_TABLE": processed_docs_table.table_name,
            "JOB_RUNS_TABLE": job_runs_table.table_name,
            "SNS_ALERT_TOPIC_ARN": self.alert_topic.topic_arn,
        }

        # ---------------------------------------------------------------
        # Scraper Lambda Functions
        # ---------------------------------------------------------------
        sec_lambda = self._create_lambda(
            "SECAgent", "src.scrapers.sec_agent.handler.handler",
            memory=512, timeout=900, env=common_env,
        )

        company_info_lambda = self._create_lambda(
            "CompanyInfoAgent", "src.scrapers.company_info_agent.handler.handler",
            memory=512, timeout=900, env=common_env,
        )

        reddit_lambda = self._create_lambda(
            "RedditAgent", "src.scrapers.reddit_agent.handler.handler",
            memory=512, timeout=900, env=common_env,
        )

        x_lambda = self._create_lambda(
            "XAgent", "src.scrapers.x_agent.handler.handler",
            memory=512, timeout=900, env=common_env,
        )

        # ---------------------------------------------------------------
        # Analyzer Lambda Functions
        # ---------------------------------------------------------------
        sentiment_lambda = self._create_lambda(
            "SentimentAnalyzer", "src.analyzers.sentiment_analyzer.handler.handler",
            memory=256, timeout=600, env=common_env,
        )

        impact_lambda = self._create_lambda(
            "ImpactScorer", "src.analyzers.impact_scorer.handler.handler",
            memory=256, timeout=300, env=common_env,
        )

        # ---------------------------------------------------------------
        # Grant permissions
        # ---------------------------------------------------------------
        all_lambdas = [
            sec_lambda, company_info_lambda, reddit_lambda, x_lambda,
            sentiment_lambda, impact_lambda,
        ]

        for fn in all_lambdas:
            raw_bucket.grant_read_write(fn)
            analysis_table.grant_read_write_data(fn)
            processed_docs_table.grant_read_write_data(fn)
            job_runs_table.grant_read_write_data(fn)
            reddit_secret.grant_read(fn)
            x_secret.grant_read(fn)
            llm_secret.grant_read(fn)

        self.alert_topic.grant_publish(impact_lambda)

        # ---------------------------------------------------------------
        # Step Functions State Machine
        # ---------------------------------------------------------------

        # Scraper tasks (run in parallel)
        sec_task = sfn_tasks.LambdaInvoke(
            self, "RunSECAgent",
            lambda_function=sec_lambda,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
        )
        sec_task.add_retry(max_attempts=2, interval=Duration.seconds(30))

        company_info_task = sfn_tasks.LambdaInvoke(
            self, "RunCompanyInfoAgent",
            lambda_function=company_info_lambda,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
        )
        company_info_task.add_retry(max_attempts=2, interval=Duration.seconds(30))

        reddit_task = sfn_tasks.LambdaInvoke(
            self, "RunRedditAgent",
            lambda_function=reddit_lambda,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
        )
        reddit_task.add_retry(max_attempts=2, interval=Duration.seconds(30))

        x_task = sfn_tasks.LambdaInvoke(
            self, "RunXAgent",
            lambda_function=x_lambda,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
        )
        x_task.add_retry(max_attempts=2, interval=Duration.seconds(30))

        # Parallel scraping
        scrape_parallel = sfn.Parallel(
            self, "ScrapeAllSources",
            result_path="$.scrape_results",
        )
        scrape_parallel.branch(sec_task)
        scrape_parallel.branch(company_info_task)
        scrape_parallel.branch(reddit_task)
        scrape_parallel.branch(x_task)

        # Add catch to continue on scraper failures
        scrape_parallel.add_catch(
            handler=sfn.Pass(self, "ScraperErrorHandler"),
            errors=["States.ALL"],
            result_path="$.scraper_error",
        )

        # Collect S3 keys from scraper outputs
        collect_keys = sfn.Pass(
            self, "CollectS3Keys",
            comment="Aggregate scraped document S3 keys for analysis",
        )

        # Sentiment analysis
        sentiment_task = sfn_tasks.LambdaInvoke(
            self, "RunSentimentAnalyzer",
            lambda_function=sentiment_lambda,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
        )
        sentiment_task.add_retry(max_attempts=2, interval=Duration.seconds(60))
        sentiment_task.add_catch(
            handler=sfn.Pass(self, "SentimentErrorHandler"),
            errors=["States.ALL"],
            result_path="$.sentiment_error",
        )

        # Impact scoring
        impact_task = sfn_tasks.LambdaInvoke(
            self, "RunImpactScorer",
            lambda_function=impact_lambda,
            output_path="$.Payload",
            retry_on_service_exceptions=True,
        )
        impact_task.add_retry(max_attempts=2, interval=Duration.seconds(30))
        impact_task.add_catch(
            handler=sfn.Pass(self, "ImpactErrorHandler"),
            errors=["States.ALL"],
            result_path="$.impact_error",
        )

        # Chain: scrape → collect → analyze → score
        definition = (
            scrape_parallel
            .next(collect_keys)
            .next(sentiment_task)
            .next(impact_task)
        )

        state_machine = sfn.StateMachine(
            self, "PipelineStateMachine",
            state_machine_name="InvestingAssistant-Pipeline",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(1),
            tracing_enabled=True,
        )

        # Export for cross-stack reference
        self.state_machine_arn = state_machine.state_machine_arn
        self.state_machine = state_machine

        # ---------------------------------------------------------------
        # EventBridge Scheduler — every 12 hours
        # ---------------------------------------------------------------
        events.Rule(
            self, "PipelineSchedule",
            rule_name="InvestingAssistant-Schedule",
            schedule=events.Schedule.rate(Duration.hours(12)),
            targets=[events_targets.SfnStateMachine(state_machine)],
        )

        # ---------------------------------------------------------------
        # Outputs
        # ---------------------------------------------------------------
        cdk.CfnOutput(self, "StateMachineArn", value=state_machine.state_machine_arn)
        cdk.CfnOutput(self, "AlertTopicArn", value=self.alert_topic.topic_arn)

    def _create_lambda(
        self,
        id: str,
        handler: str,
        *,
        memory: int = 256,
        timeout: int = 300,
        env: dict = None,
    ) -> _lambda.Function:
        """Create a Lambda function with standard configuration."""
        return _lambda.Function(
            self,
            id,
            function_name=f"InvestingAssistant-{id}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            code=_lambda.Code.from_asset(
                PROJECT_ROOT,
                exclude=[
                    ".venv/**", "node_modules/**", ".git/**", ".local_data/**",
                    "infrastructure/**", "*.pyc", "__pycache__/**",
                    "src/frontend/**", "scripts/**", "*.egg-info/**",
                    ".env", ".env.example", "*.md", ".gitignore",
                    ".DS_Store", "build/**",
                ],
            ),
            handler=handler,
            layers=[self._deps_layer],
            memory_size=memory,
            timeout=Duration.seconds(timeout),
            environment=env or {},
            tracing=_lambda.Tracing.ACTIVE,
        )
