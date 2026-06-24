"""
API Stack — API Gateway HTTP API + Lambda backend.
"""

from pathlib import Path
from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_stepfunctions as sfn,
)

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


class ApiStack(Stack):
    """API Gateway HTTP API backed by a FastAPI Lambda."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        analysis_table: dynamodb.ITable,
        processed_docs_table: dynamodb.ITable,
        job_runs_table: dynamodb.ITable,
        raw_bucket: s3.IBucket,
        state_machine_arn: str = "",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # Auth config from CDK context
        # ---------------------------------------------------------------
        jwt_secret = self.node.try_get_context("jwt_secret") or "investing-assistant-dev-secret-change-me"
        admin_username = self.node.try_get_context("admin_username") or "admin"
        admin_password = self.node.try_get_context("admin_password") or "admin"
        google_client_id = self.node.try_get_context("google_client_id") or ""

        # ---------------------------------------------------------------
        # Lambda Layer — Python dependencies (built in CI/CD)
        # ---------------------------------------------------------------
        layer_path = str(Path(PROJECT_ROOT) / "build" / "lambda-layer")
        deps_layer = _lambda.LayerVersion(
            self, "PythonDepsLayer",
            code=_lambda.Code.from_asset(layer_path),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            description="Python dependencies for InvestingAssistant API",
        )

        # ---------------------------------------------------------------
        # API Lambda
        # ---------------------------------------------------------------
        api_lambda = _lambda.Function(
            self,
            "ApiFunction",
            function_name="InvestingAssistant-Api",
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
            handler="src.api.handler.handler",
            layers=[deps_layer],
            memory_size=256,
            timeout=Duration.seconds(30),
            environment={
                "INVESTING_ASSISTANT_ENV": "dev",
                "S3_RAW_BUCKET": raw_bucket.bucket_name,
                "ANALYSIS_TABLE": analysis_table.table_name,
                "PROCESSED_DOCS_TABLE": processed_docs_table.table_name,
                "JOB_RUNS_TABLE": job_runs_table.table_name,
                "JWT_SECRET": jwt_secret,
                "ADMIN_USERNAME": admin_username,
                "ADMIN_PASSWORD": admin_password,
                "VITE_GOOGLE_CLIENT_ID": google_client_id,
                "STATE_MACHINE_ARN": state_machine_arn,
            },
            tracing=_lambda.Tracing.ACTIVE,
        )

        # Grant read/write permissions (API creates job runs, stores analysis, writes S3)
        analysis_table.grant_read_write_data(api_lambda)
        processed_docs_table.grant_read_write_data(api_lambda)
        job_runs_table.grant_read_write_data(api_lambda)
        raw_bucket.grant_read_write(api_lambda)

        # Grant API Lambda permission to trigger and monitor the pipeline
        if state_machine_arn:
            # Execution ARN pattern: replace :stateMachine: with :execution: + wildcard
            execution_arn = state_machine_arn.replace(":stateMachine:", ":execution:") + ":*"
            api_lambda.add_to_role_policy(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["states:StartExecution"],
                    resources=[state_machine_arn],
                )
            )
            api_lambda.add_to_role_policy(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "states:DescribeExecution",
                        "states:GetExecutionHistory",
                    ],
                    # state_machine_arn is a CDK token, so .replace() won't work.
                    # Use Fn::Sub to construct: arn:aws:states:REGION:ACCOUNT:execution:NAME:*
                    resources=[
                        cdk.Fn.join("", [
                            cdk.Fn.select(0, cdk.Fn.split(":stateMachine:", state_machine_arn)),
                            ":execution:",
                            cdk.Fn.select(1, cdk.Fn.split(":stateMachine:", state_machine_arn)),
                            ":*",
                        ])
                    ],
                )
            )

        # Grant API Lambda permission to read CloudWatch logs from pipeline Lambdas
        api_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:FilterLogEvents",
                    "logs:GetLogEvents",
                    "logs:DescribeLogStreams",
                ],
                resources=[
                    cdk.Fn.sub(
                        "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/InvestingAssistant-*:*"
                    )
                ],
            )
        )
        # ---------------------------------------------------------------
        # API Gateway HTTP API
        # ---------------------------------------------------------------
        http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            api_name="InvestingAssistant-HttpApi",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_headers=["*"],
                max_age=Duration.hours(1),
            ),
        )

        # Default integration — all routes go to the FastAPI Lambda
        integration = apigwv2_integrations.HttpLambdaIntegration(
            "ApiIntegration", handler=api_lambda,
        )

        http_api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=integration,
        )

        # Also handle root path
        http_api.add_routes(
            path="/",
            methods=[apigwv2.HttpMethod.GET],
            integration=integration,
        )

        # ---------------------------------------------------------------
        # Outputs
        # ---------------------------------------------------------------
        self.api_url = http_api.url or ""

        cdk.CfnOutput(self, "ApiUrl", value=self.api_url)
        cdk.CfnOutput(self, "ApiLambdaArn", value=api_lambda.function_arn)
