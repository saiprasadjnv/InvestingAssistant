"""
Storage Stack — Stateful resources (S3 + DynamoDB).

These resources use RETAIN removal policy to prevent accidental data loss.
"""

from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
)


class StorageStack(Stack):
    """S3 bucket for raw documents and DynamoDB tables for analysis results."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # S3 Bucket — Raw scraped documents
        # ---------------------------------------------------------------
        self.raw_bucket = s3.Bucket(
            self,
            "RawDocumentsBucket",
            bucket_name=f"investingassistant-raw-{cdk.Aws.ACCOUNT_ID}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="TransitionToIA",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        ),
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=Duration.days(90),
                        ),
                    ],
                ),
            ],
        )

        # ---------------------------------------------------------------
        # DynamoDB — Analysis Results
        # ---------------------------------------------------------------
        self.analysis_table = dynamodb.Table(
            self,
            "AnalysisResultsTable",
            table_name="InvestingAssistant-AnalysisResults",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PROVISIONED,
            read_capacity=25,
            write_capacity=25,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )

        # GSI1: Source-based time queries
        self.analysis_table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
            read_capacity=5,
            write_capacity=5,
        )

        # GSI2: Impact tier queries (high-confidence findings)
        self.analysis_table.add_global_secondary_index(
            index_name="GSI2",
            partition_key=dynamodb.Attribute(
                name="GSI2PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="GSI2SK", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
            read_capacity=5,
            write_capacity=5,
        )

        # ---------------------------------------------------------------
        # DynamoDB — Processed Documents (deduplication)
        # ---------------------------------------------------------------
        self.processed_docs_table = dynamodb.Table(
            self,
            "ProcessedDocsTable",
            table_name="InvestingAssistant-ProcessedDocuments",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PROVISIONED,
            read_capacity=25,
            write_capacity=25,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ---------------------------------------------------------------
        # DynamoDB — Job Runs (pipeline metrics)
        # ---------------------------------------------------------------
        self.job_runs_table = dynamodb.Table(
            self,
            "JobRunsTable",
            table_name="InvestingAssistant-JobRuns",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PROVISIONED,
            read_capacity=5,
            write_capacity=5,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ---------------------------------------------------------------
        # DynamoDB — User Data (per-user preferences & tracked companies)
        # ---------------------------------------------------------------
        self.user_data_table = dynamodb.Table(
            self,
            "UserDataTable",
            table_name="InvestingAssistant-UserData",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )

        # ---------------------------------------------------------------
        # Outputs
        # ---------------------------------------------------------------
        cdk.CfnOutput(self, "RawBucketName", value=self.raw_bucket.bucket_name)
        cdk.CfnOutput(self, "AnalysisTableName", value=self.analysis_table.table_name)
        cdk.CfnOutput(self, "ProcessedDocsTableName", value=self.processed_docs_table.table_name)
        cdk.CfnOutput(self, "JobRunsTableName", value=self.job_runs_table.table_name)
        cdk.CfnOutput(self, "UserDataTableName", value=self.user_data_table.table_name)
