import boto3
import os
from botocore.config import Config

REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")
S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME", "automotive-hackathon-wheelchair")

# Configure Boto3 clients
aws_config = Config(
    connect_timeout=2,
    read_timeout=10,
    retries={'max_attempts': 1}
)

polly = boto3.client('polly', region_name=REGION, config=aws_config)
response = polly.describe_voices()

# Filter for Vietnamese or print all supported languages
vi_voices = [v for v in response['Voices'] if v['LanguageCode'].startswith('vi')]
print("Vietnamese voices found:", vi_voices)  # Output: []