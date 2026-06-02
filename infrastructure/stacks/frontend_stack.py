"""
Frontend Stack — S3 static hosting + CloudFront CDN.
"""

from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
)
from pathlib import Path

FRONTEND_DIST = str(Path(__file__).resolve().parent.parent.parent / "src" / "frontend" / "dist")


class FrontendStack(Stack):
    """S3 + CloudFront for hosting the React dashboard."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        api_url: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # S3 Bucket — Static assets
        # ---------------------------------------------------------------
        site_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"investingassistant-frontend-{cdk.Aws.ACCOUNT_ID}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # ---------------------------------------------------------------
        # CloudFront Distribution
        # ---------------------------------------------------------------
        # Origin Access Identity for S3
        oai = cloudfront.OriginAccessIdentity(
            self, "OAI",
            comment="InvestingAssistant Frontend OAI",
        )
        site_bucket.grant_read(oai)

        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            comment="InvestingAssistant Dashboard",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(site_bucket, origin_access_identity=oai),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            default_root_object="index.html",
            error_responses=[
                # SPA routing: return index.html for 403/404
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        # ---------------------------------------------------------------
        # Deploy static files to S3
        # ---------------------------------------------------------------
        s3deploy.BucketDeployment(
            self,
            "DeployFrontend",
            sources=[s3deploy.Source.asset(FRONTEND_DIST)],
            destination_bucket=site_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # ---------------------------------------------------------------
        # Outputs
        # ---------------------------------------------------------------
        self.distribution_url = f"https://{distribution.distribution_domain_name}"

        cdk.CfnOutput(self, "FrontendUrl", value=self.distribution_url)
        cdk.CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        cdk.CfnOutput(self, "FrontendBucketName", value=site_bucket.bucket_name)
        cdk.CfnOutput(self, "ApiUrl", value=api_url)
