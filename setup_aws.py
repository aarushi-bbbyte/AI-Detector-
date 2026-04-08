"""
setup_aws.py  —  run once to create all AWS resources
─────────────────────────────────────────────────────
Usage:
    pip install boto3
    python setup_aws.py

This creates:
  - S3 bucket (document storage, replaces MinIO)
  - SQS queue (job queue, replaces Redis/Celery)
  - DynamoDB table (results store)
  - IAM role for Lambda functions

Prints the env vars you need to copy into .env.aws at the end.
"""

import boto3, json, time
from botocore.exceptions import ClientError

REGION     = "us-east-1"
BUCKET     = "plagiarism-ai-docs"        # must be globally unique — add your name e.g. "plagiarism-ai-docs-shubhangi"
QUEUE_NAME = "plagiarism-ai-jobs"
TABLE_NAME = "plagiarism-ai-results"
ROLE_NAME  = "plagiarism-lambda-role"

s3       = boto3.client("s3",       region_name=REGION)
sqs      = boto3.client("sqs",      region_name=REGION)
dynamodb = boto3.client("dynamodb", region_name=REGION)
iam      = boto3.client("iam",      region_name=REGION)
sts      = boto3.client("sts",      region_name=REGION)
ACCOUNT_ID = sts.get_caller_identity()["Account"]


def create_bucket():
    print(f"\n[S3] Creating bucket: {BUCKET}")
    try:
        if REGION == "us-east-1":
            s3.create_bucket(Bucket=BUCKET)
        else:
            s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        s3.put_public_access_block(Bucket=BUCKET, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        })
        print(f"[S3] ✓ Created: {BUCKET}")
    except ClientError as e:
        if "BucketAlreadyOwnedByYou" in str(e):
            print(f"[S3] Already exists — OK")
        else:
            raise


def create_queue():
    print(f"\n[SQS] Creating queue: {QUEUE_NAME}")
    try:
        resp = sqs.create_queue(QueueName=QUEUE_NAME, Attributes={
            "VisibilityTimeout": "300",
            "MessageRetentionPeriod": "86400",
        })
        url  = resp["QueueUrl"]
        arn  = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        print(f"[SQS] ✓ Created: {url}")
        return url, arn
    except ClientError as e:
        if "QueueAlreadyExists" in str(e):
            url = sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
            arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
            print(f"[SQS] Already exists — OK")
            return url, arn
        raise


def create_table():
    print(f"\n[DynamoDB] Creating table: {TABLE_NAME}")
    try:
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=TABLE_NAME)
        print(f"[DynamoDB] ✓ Created: {TABLE_NAME}")
    except ClientError as e:
        if "ResourceInUseException" in str(e):
            print(f"[DynamoDB] Already exists — OK")
        else:
            raise


def create_iam_role():
    print(f"\n[IAM] Creating Lambda role: {ROLE_NAME}")
    trust = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
    try:
        role = iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=trust)
        role_arn = role["Role"]["Arn"]
    except ClientError as e:
        if "EntityAlreadyExists" in str(e):
            role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
            print(f"[IAM] Already exists — OK")
        else:
            raise

    policies = [
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        "arn:aws:iam::aws:policy/AmazonS3FullAccess",
        "arn:aws:iam::aws:policy/AmazonSQSFullAccess",
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
    ]
    for p in policies:
        try:
            iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=p)
        except ClientError:
            pass

    print(f"[IAM] ✓ Role ARN: {role_arn}")
    time.sleep(10)  # IAM propagation delay
    return role_arn


if __name__ == "__main__":
    create_bucket()
    queue_url, queue_arn = create_queue()
    create_table()
    role_arn = create_iam_role()

    print("\n" + "="*60)
    print("SUCCESS — copy these into your .env.aws file:")
    print("="*60)
    print(f"AWS_REGION={REGION}")
    print(f"AWS_ACCOUNT_ID={ACCOUNT_ID}")
    print(f"S3_BUCKET_NAME={BUCKET}")
    print(f"SQS_QUEUE_URL={queue_url}")
    print(f"DYNAMODB_TABLE={TABLE_NAME}")
    print(f"LAMBDA_ROLE_ARN={role_arn}")
    print("="*60)
