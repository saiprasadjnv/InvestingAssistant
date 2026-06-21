"""
Frontend Stack — S3 static hosting + CloudFront CDN + Custom Domain.
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
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as targets,
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
        domain_name: str = "",
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
        # Custom Domain — Route 53 + ACM (if domain_name provided)
        # ---------------------------------------------------------------
        certificate = None
        domain_names = None
        hosted_zone = None

        if domain_name:
            # Create a Route 53 public hosted zone for the domain
            hosted_zone = route53.PublicHostedZone(
                self, "HostedZone",
                zone_name=domain_name,
                comment=f"Hosted zone for {domain_name}",
            )

            # ACM certificate with DNS validation (must be in us-east-1 for CloudFront)
            certificate = acm.Certificate(
                self, "SiteCertificate",
                domain_name=domain_name,
                subject_alternative_names=[f"www.{domain_name}"],
                validation=acm.CertificateValidation.from_dns(hosted_zone),
            )

            domain_names = [domain_name, f"www.{domain_name}"]

        # ---------------------------------------------------------------
        # CloudFront Distribution
        # ---------------------------------------------------------------
        # Origin Access Identity for S3
        oai = cloudfront.OriginAccessIdentity(
            self, "OAI",
            comment="InvestingAssistant Frontend OAI",
        )
        site_bucket.grant_read(oai)

        # Extract API Gateway domain from URL token
        # api_url is like "https://abc123.execute-api.us-east-1.amazonaws.com/"
        api_domain = cdk.Fn.select(2, cdk.Fn.split("/", api_url))

        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            comment="InvestingAssistant Dashboard",
            domain_names=domain_names,
            certificate=certificate,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(site_bucket, origin_access_identity=oai),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,  # SPA needs no-cache for index.html
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(api_domain),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                ),
            },
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
        # DNS Records — point domain to CloudFront
        # ---------------------------------------------------------------
        if hosted_zone and domain_name:
            # Root domain → CloudFront
            route53.ARecord(
                self, "SiteARecord",
                zone=hosted_zone,
                record_name=domain_name,
                target=route53.RecordTarget.from_alias(
                    targets.CloudFrontTarget(distribution)
                ),
            )
            # www subdomain → CloudFront
            route53.ARecord(
                self, "WwwARecord",
                zone=hosted_zone,
                record_name=f"www.{domain_name}",
                target=route53.RecordTarget.from_alias(
                    targets.CloudFrontTarget(distribution)
                ),
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

        if domain_name:
            cdk.CfnOutput(self, "CustomDomainUrl", value=f"https://{domain_name}")
            cdk.CfnOutput(
                self, "NameServers",
                value=cdk.Fn.join(", ", hosted_zone.hosted_zone_name_servers),
                description="Set these as your domain's nameservers at your registrar",
            )
