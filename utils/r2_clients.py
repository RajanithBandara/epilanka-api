import boto3
import os

r2_client = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("R2_SECRET_KEY"),
    region_name="auto",
)

BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL")
