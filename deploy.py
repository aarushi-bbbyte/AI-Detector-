"""
deploy.py  —  deploys all 4 Lambdas + API Gateway
──────────────────────────────────────────────────
Routes:
  POST /analyze                → upload_handler
  GET  /results/{job_id}       → results_handler
  GET  /history/{session_id}   → results_handler
  POST /plagiarism             → plagiarism_checker  ← NEW

Usage (PowerShell):
    $env:AWS_REGION="us-east-1"
    $env:AWS_ACCOUNT_ID="YOUR_ACCOUNT_ID"
    $env:S3_BUCKET_NAME="plagiarism-ai-docs"
    $env:SQS_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/..."
    $env:DYNAMODB_TABLE="plagiarism-ai-results"
    $env:LAMBDA_ROLE_ARN="arn:aws:iam::...role/plagiarism-lambda-role"
    $env:HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxx"

    python deploy.py
"""
import os, io, zipfile, time
import boto3
from botocore.exceptions import ClientError

REGION     = os.environ["AWS_REGION"]
ACCOUNT_ID = os.environ["AWS_ACCOUNT_ID"]
ROLE_ARN   = os.environ["LAMBDA_ROLE_ARN"]
HF_TOKEN   = os.environ["HF_TOKEN"]

ENV = {"Variables": {
    "S3_BUCKET_NAME": os.environ["S3_BUCKET_NAME"],
    "SQS_QUEUE_URL":  os.environ["SQS_QUEUE_URL"],
    "DYNAMODB_TABLE": os.environ["DYNAMODB_TABLE"],
    "HF_TOKEN":       HF_TOKEN,
}}

lm    = boto3.client("lambda",        region_name=REGION)
apigw = boto3.client("apigatewayv2",  region_name=REGION)
sqs   = boto3.client("sqs",           region_name=REGION)


def zip_file(folder_path):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path  = os.path.relpath(full_path, folder_path)
                print(f"  Adding: {rel_path}")
                z.write(full_path, rel_path)
    zip_buffer.seek(0)
    data = zip_buffer.read()
    print(f"  ZIP SIZE: {len(data)} bytes")
    return data


def deploy_lambda(name, path, memory=256, timeout=60):
    print(f"\n[Lambda] Deploying {name}...")
    zb = zip_file(path)
    try:
        lm.update_function_code(FunctionName=name, ZipFile=zb)
        waiter = lm.get_waiter("function_updated")
        waiter.wait(FunctionName=name)
        lm.update_function_configuration(
            FunctionName=name, Environment=ENV,
            Timeout=timeout, MemorySize=memory)
        waiter = lm.get_waiter("function_updated")
        waiter.wait(FunctionName=name)
        print(f"[Lambda] ✓ Updated {name}")
    except lm.exceptions.ResourceNotFoundException:
        lm.create_function(
            FunctionName=name, Runtime="python3.11", Role=ROLE_ARN,
            Handler="handler.handler", Code={"ZipFile": zb},
            Environment=ENV, Timeout=timeout, MemorySize=memory)
        time.sleep(8)
        print(f"[Lambda] ✓ Created {name}")
    return lm.get_function(FunctionName=name)["Configuration"]["FunctionArn"]


def wire_sqs(fn_name):
    print(f"\n[SQS] Wiring queue → {fn_name}...")
    q_arn = sqs.get_queue_attributes(
        QueueUrl=os.environ["SQS_QUEUE_URL"],
        AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    existing = lm.list_event_source_mappings(FunctionName=fn_name)["EventSourceMappings"]
    if any(m["EventSourceArn"] == q_arn for m in existing):
        print("[SQS] Trigger already exists — OK")
        return
    lm.create_event_source_mapping(
        EventSourceArn=q_arn, FunctionName=fn_name,
        BatchSize=1, FunctionResponseTypes=["ReportBatchItemFailures"])
    print("[SQS] ✓ Trigger created")


def add_permission(fn_name, api_id):
    try:
        lm.add_permission(
            FunctionName=fn_name, StatementId=f"apigw-{fn_name}",
            Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/*")
    except lm.exceptions.ResourceConflictException:
        pass


def create_api(upload_arn, results_arn, plagcheck_arn):
    print("\n[API Gateway] Creating HTTP API...")
    try:
        api    = apigw.create_api(
            Name="plagiarism-ai-api", ProtocolType="HTTP",
            CorsConfiguration={
                "AllowOrigins": ["*"],
                "AllowMethods": ["GET", "POST", "OPTIONS"],
                "AllowHeaders": ["Content-Type"],
            })
        api_id = api["ApiId"]

        ui = apigw.create_integration(ApiId=api_id, IntegrationType="AWS_PROXY",
                                       IntegrationUri=upload_arn,    PayloadFormatVersion="2.0")
        ri = apigw.create_integration(ApiId=api_id, IntegrationType="AWS_PROXY",
                                       IntegrationUri=results_arn,   PayloadFormatVersion="2.0")
        pi = apigw.create_integration(ApiId=api_id, IntegrationType="AWS_PROXY",
                                       IntegrationUri=plagcheck_arn, PayloadFormatVersion="2.0")

        apigw.create_route(ApiId=api_id, RouteKey="POST /analyze",
                           Target=f"integrations/{ui['IntegrationId']}")
        apigw.create_route(ApiId=api_id, RouteKey="GET /results/{job_id}",
                           Target=f"integrations/{ri['IntegrationId']}")
        apigw.create_route(ApiId=api_id, RouteKey="GET /history/{session_id}",
                           Target=f"integrations/{ri['IntegrationId']}")
        apigw.create_route(ApiId=api_id, RouteKey="POST /plagiarism",
                           Target=f"integrations/{pi['IntegrationId']}")

        apigw.create_stage(ApiId=api_id, StageName="prod", AutoDeploy=True)

        add_permission("plagiarism-upload-handler",  api_id)
        add_permission("plagiarism-results-handler", api_id)
        add_permission("plagiarism-checker",         api_id)

        endpoint = f"https://{api_id}.execute-api.{REGION}.amazonaws.com/prod"
        print(f"[API Gateway] ✓ Live at: {endpoint}")
        return endpoint

    except Exception as e:
        if "ConflictException" in str(type(e)):
            apis     = apigw.get_apis()["Items"]
            existing = next((a for a in apis if a["Name"] == "plagiarism-ai-api"), None)
            if existing:
                api_id = existing["ApiId"]
                _add_missing_routes(api_id, results_arn, plagcheck_arn)
                endpoint = f"https://{api_id}.execute-api.{REGION}.amazonaws.com/prod"
                print(f"[API Gateway] Already exists: {endpoint}")
                return endpoint
        raise


def _add_missing_routes(api_id, results_arn, plagcheck_arn):
    """Idempotently add any missing routes to an existing API."""
    routes        = apigw.get_routes(ApiId=api_id).get("Items", [])
    existing_keys = {r.get("RouteKey") for r in routes}
    integrations  = apigw.get_integrations(ApiId=api_id).get("Items", [])

    def _get_or_create_integration(arn):
        match = next((i for i in integrations if arn in i.get("IntegrationUri", "")), None)
        if match:
            return match["IntegrationId"]
        new = apigw.create_integration(ApiId=api_id, IntegrationType="AWS_PROXY",
                                        IntegrationUri=arn, PayloadFormatVersion="2.0")
        return new["IntegrationId"]

    if "GET /history/{session_id}" not in existing_keys:
        iid = _get_or_create_integration(results_arn)
        apigw.create_route(ApiId=api_id, RouteKey="GET /history/{session_id}",
                           Target=f"integrations/{iid}")
        print("[API Gateway] ✓ /history route added")

    if "POST /plagiarism" not in existing_keys:
        iid = _get_or_create_integration(plagcheck_arn)
        apigw.create_route(ApiId=api_id, RouteKey="POST /plagiarism",
                           Target=f"integrations/{iid}")
        print("[API Gateway] ✓ /plagiarism route added")


if __name__ == "__main__":
    upload_arn    = deploy_lambda("plagiarism-upload-handler",
                                  "lambdas/upload_handler",     memory=256, timeout=30)
    results_arn   = deploy_lambda("plagiarism-results-handler",
                                  "lambdas/results_handler",    memory=256, timeout=30)
    _             = deploy_lambda("plagiarism-nlp-worker",
                                  "lambdas/nlp_worker",         memory=256, timeout=120)
    plagcheck_arn = deploy_lambda("plagiarism-checker",
                                  "lambdas/plagiarism_checker", memory=256, timeout=30)

    wire_sqs("plagiarism-nlp-worker")
    endpoint = create_api(upload_arn, results_arn, plagcheck_arn)

    print("\n" + "=" * 60)
    print("DEPLOYMENT COMPLETE")
    print("=" * 60)
    print(f"API: {endpoint}")
    print(f"\nPOST {endpoint}/analyze")
    print('     body: {"text":"...","session_id":"...","filename":"...","file_type":"text|pdf|docx"}')
    print(f"GET  {endpoint}/results/{{job_id}}")
    print(f"GET  {endpoint}/history/{{session_id}}")
    print(f"POST {endpoint}/plagiarism")
    print('     body: {"text1":"...","text2":"...","name1":"Doc A","name2":"Doc B"}')
    print(f"\nUpdate frontend/.env:")
    print(f"VITE_API_BASE_URL={endpoint}")
    print("=" * 60)