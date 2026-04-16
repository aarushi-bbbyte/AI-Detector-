# ◈ AIScope — Cloud-Based AI Content & Plagiarism Detector

A full-stack document analysis tool with two modes: **AI Content Detection** (is this text AI-generated?) and **Plagiarism Detection** (are these two documents copied from each other?). The entire stack — frontend and backend — runs on AWS.

---

## Features

### 🔍 AI Detection
- Detects AI-generated text via `roberta-base-openai-detector` (125M param RoBERTa, fine-tuned on GPT-2/GPT-3 outputs)
- Paste text or upload **PDF, DOCX, or TXT** — text extracted client-side, only plain text sent to backend
- **Version history sidebar** — every submission saved per browser session with AI%, timestamp, and document preview
- **Version labels** — tag submissions (e.g. "Draft 2", "Final") for easy comparison
- **Chunked inference** — documents split into 512-char chunks, scored individually, then averaged
- **Confidence scoring** — `confidence = |score − 0.5| × 2` with high / medium / low certainty labels
- Per-chunk score bar chart in the results view
- **⬇ Download PDF report** — full dark-themed report with score, confidence, chunk chart, and document preview, generated entirely in the browser

### 📄 Plagiarism Check
- Compare **two documents** against each other for copied content
- Upload PDF, DOCX, or TXT for either document, or paste text directly
- **Sentence-level matching** — Jaccard trigram similarity finds near-identical passages
- **TF-IDF cosine similarity** — overall document-level vocabulary overlap score
- **Colour-coded highlights** — matching passages highlighted in both documents simultaneously; hover a match to locate it
- Overall similarity %, sentence coverage %, and match count
- Verdict: High plagiarism / Significant overlap / Some similarity / Minor / Original

### ☁️ Infrastructure
- Fully serverless — no servers to manage, scales to zero when idle
- Frontend hosted on **S3 + CloudFront** — static website hosting with HTTPS and global CDN
- Asynchronous AI detection via SQS queue — frontend polls for results
- Plagiarism check is synchronous — pure Python stdlib, no ML model, instant response
- IP-based rate limiting — max 10 requests per IP per hour
- `deploy.py` is fully idempotent — safe to run multiple times, never creates duplicate APIs

---

## Architecture

```
User's Browser
      │
      ▼
Amazon CloudFront  ←── caches + serves over HTTPS
      │
      ▼
Amazon S3 (frontend bucket)  ←── React static files (HTML/CSS/JS)


User clicks Analyse
      │
      ▼
Amazon CloudFront / S3 (frontend) sends request to:
      │
      ▼
AWS API Gateway (HTTP API)
      │
      ├── POST /analyze  ──────────► upload_handler Lambda
      │                                    │
      │                              ┌─────┼──────┐
      │                              ▼     ▼      ▼
      │                             S3    SQS  DynamoDB
      │                                    │
      │                                    ▼ (trigger)
      │                             nlp_worker Lambda
      │                                    │
      │                             HuggingFace API (external)
      │                                    │
      │                                    ▼
      │                                DynamoDB
      │
      ├── GET /results/{job_id} ───► results_handler Lambda
      ├── GET /history/{session_id} ► results_handler Lambda
      │                                    │
      │                                DynamoDB
      │
      └── POST /plagiarism ─────────► plagiarism_checker Lambda
                                       (pure Python, no external API)
```

**AWS services:** S3 · CloudFront · Lambda · API Gateway · SQS · DynamoDB · IAM

---

## Project Structure

```
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Main app — tabs, AI detection, history sidebar
│   │   ├── PlagiarismChecker.jsx  # Plagiarism tab — two-doc upload, highlights
│   │   ├── reportGenerator.js     # Client-side PDF report generation (jsPDF)
│   │   ├── App.css                # Styles
│   │   └── main.jsx               # Entry point
│   ├── .env.example
│   ├── package.json
│   └── vite.config.js
│
├── lambdas/
│   ├── upload_handler/
│   │   └── handler.py       # POST /analyze — rate limiting, S3 upload, SQS enqueue
│   ├── results_handler/
│   │   └── handler.py       # GET /results/{job_id}, GET /history/{session_id}
│   ├── nlp_worker/
│   │   └── handler.py       # SQS consumer — HuggingFace inference
│   └── plagiarism_checker/
│       └── handler.py       # POST /plagiarism — sentence matching + cosine similarity
│
├── setup_aws.py             # Run once — creates S3, SQS, DynamoDB, IAM role
├── deploy.py                # Idempotent deploy — updates all Lambdas + API Gateway
└── README.md
```

---

## Setup & Deployment

### Prerequisites

- Python 3.11+
- Node.js 18+
- AWS account with CLI configured (`aws configure`)
- Free [HuggingFace account](https://huggingface.co) + access token

### 1. Create AWS resources (run once)

```bash
pip install boto3
python setup_aws.py
```

Creates the S3 documents bucket, SQS queue, DynamoDB table, and IAM role. Copy the printed output for the next step.

### 2. Set environment variables

```powershell
# PowerShell
$env:AWS_REGION="us-east-1"
$env:AWS_ACCOUNT_ID="YOUR_ACCOUNT_ID"
$env:S3_BUCKET_NAME="plagiarism-ai-docs"
$env:SQS_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/YOUR_ACCOUNT/plagiarism-ai-jobs"
$env:DYNAMODB_TABLE="plagiarism-ai-results"
$env:LAMBDA_ROLE_ARN="arn:aws:iam::YOUR_ACCOUNT:role/plagiarism-lambda-role"
$env:HF_TOKEN="hf_your_token_here"
```

```bash
# Bash / macOS / Linux
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID="YOUR_ACCOUNT_ID"
export S3_BUCKET_NAME="plagiarism-ai-docs"
export SQS_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/YOUR_ACCOUNT/plagiarism-ai-jobs"
export DYNAMODB_TABLE="plagiarism-ai-results"
export LAMBDA_ROLE_ARN="arn:aws:iam::YOUR_ACCOUNT:role/plagiarism-lambda-role"
export HF_TOKEN="hf_your_token_here"
```

### 3. Deploy all Lambdas + API Gateway

```bash
python deploy.py
```

Safe to run multiple times — finds the existing API by name and patches it, never creates duplicates.

### 4. Build and deploy the frontend (S3 + CloudFront)

```bash
cd frontend
npm install
npm run build
```

Then in AWS Console:

**S3:** Create a new bucket for the frontend → enable static website hosting → upload the contents of the `dist/` folder → set bucket policy to allow public read.

**CloudFront:** Create a distribution → set the S3 bucket as the origin → set the default root object to `index.html` → create the distribution → copy the CloudFront URL.

**Set environment variable:** Before building, create `frontend/.env` from `.env.example` and set:
```
VITE_API_BASE_URL=https://your-api-id.execute-api.us-east-1.amazonaws.com/prod
```

Your app is now live at the CloudFront URL over HTTPS.

---

## Environment Variables

### Frontend (`frontend/.env`)

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | API Gateway endpoint printed by `deploy.py` |

### Backend (set before running `deploy.py`)

| Variable | Description |
|---|---|
| `AWS_REGION` | AWS region (e.g. `us-east-1`) |
| `AWS_ACCOUNT_ID` | Your 12-digit AWS account ID |
| `S3_BUCKET_NAME` | S3 documents bucket name from `setup_aws.py` |
| `SQS_QUEUE_URL` | SQS queue URL from `setup_aws.py` |
| `DYNAMODB_TABLE` | DynamoDB table name |
| `LAMBDA_ROLE_ARN` | IAM role ARN from `setup_aws.py` |
| `HF_TOKEN` | HuggingFace API token |

---

## How AI Detection Works

1. Text split into **512-character chunks** (max 20 per document)
2. Each chunk sent to HuggingFace Inference API (`roberta-base-openai-detector`)
3. Model returns probability per chunk — `FAKE` = AI, `REAL` = human
4. Chunk scores **averaged** → final score (0–1)
5. Confidence = `|score − 0.5| × 2`

| Score | Confidence | Label |
|---|---|---|
| ≥ 0.5 | > 0.7 | Likely AI |
| ≥ 0.5 | 0.3–0.7 | Possibly AI |
| < 0.5 | > 0.7 | Likely Human |
| < 0.5 | 0.3–0.7 | Possibly Human |
| any | < 0.3 | Uncertain |

---

## How Plagiarism Detection Works

1. Both documents split into sentences (min 6 words each)
2. Every sentence in Doc 1 compared to every sentence in Doc 2 using **Jaccard trigram similarity**
3. Pairs above 0.5 similarity threshold flagged as matches (greedy, no double-matching)
4. **TF-IDF cosine similarity** computed at document level for vocabulary overlap
5. Final similarity % = blend of sentence coverage + cosine similarity
6. Character offsets computed for each match → rendered as colour-coded highlights in the UI

| Similarity | Verdict |
|---|---|
| ≥ 75% | High plagiarism detected |
| ≥ 50% | Significant overlap found |
| ≥ 25% | Some similarity detected |
| ≥ 10% | Minor similarity |
| < 10% | Documents appear original |

---

## Why S3 + CloudFront for Frontend Hosting

S3 static website hosting alone only supports HTTP. CloudFront adds:

- **HTTPS** — secure access via SSL/TLS certificate (free via AWS Certificate Manager)
- **Global CDN** — files cached at edge locations worldwide, reducing latency
- **Custom domain support** — can attach a custom domain via Route 53
- **Cost efficiency** — CloudFront serves cached files, reducing direct S3 requests

This is the standard AWS pattern for hosting static web applications in production.

---

## PDF Report

Clicking **⬇ Download PDF** generates a dark-themed A4 report entirely in the browser using [jsPDF](https://github.com/parallax/jsPDF) — no backend call needed. Includes:

- Document name, version label, and analysis timestamp
- AI probability % with colour-coded gauge bar
- AI% / Human% / Raw score stat boxes
- Confidence meter with interpretation note
- Score formula breakdown
- Model details (model, chunks analysed, word count, variance)
- Document preview (first 300 characters)
- Per-chunk bar chart with colour-coded bars
- Full chunk-by-chunk score table
- Page numbers and disclaimer footer

---

## Rate Limiting

The `upload_handler` Lambda enforces a limit of **10 submissions per IP per hour**. Requests exceeding this return HTTP 429. Rate limit records are stored in DynamoDB with a 2-hour TTL and auto-deleted — no manual cleanup needed.

---

## Model Metrics

| Metric | Value | Notes |
|---|---|---|
| Accuracy | ~95% | On GPT-2 1.5B outputs vs WebText — ideal conditions |
| Test set | 10,000 samples | 5,000 human + 5,000 GPT-2 generated |
| Hardest case | Nucleus sampling outputs | Most difficult to classify |

The model was trained on GPT-2 outputs from 2019. Accuracy is lower on modern LLM outputs (GPT-4, Claude, Gemini). OpenAI recommends pairing it with human judgment rather than using it as sole evidence.

---

## Re-deploying After Changes

```bash
python deploy.py
```

Updates all 4 Lambdas, patches missing routes, refreshes CORS, redeploys the stage. For frontend changes, run `npm run build` and re-upload the `dist/` folder to the S3 frontend bucket, then invalidate the CloudFront cache.

---

## Cost

Effectively **$0** for personal/academic use:

| Service | Free tier |
|---|---|
| HuggingFace Inference API | Free |
| AWS Lambda | 1M requests/month |
| AWS API Gateway | 1M requests/month |
| AWS SQS | 1M requests/month |
| AWS DynamoDB | 25 GB + 200M requests |
| AWS S3 | 5 GB storage + 20K requests |
| AWS CloudFront | 1 TB data transfer + 10M requests/month |

---

## Notes

- First AI detection after a cold start may take ~60s while the HuggingFace model loads. Subsequent runs are fast.
- AI detection results stored in DynamoDB with a **7-day TTL**, then auto-deleted.
- Plagiarism results are **not stored** — computed on demand and returned directly.
- PDF reports generated **entirely client-side** — jsPDF loaded from CDN on first use, no install needed.
- Version history scoped to browser session via `localStorage`. Clearing browser data resets it.
- PDF and DOCX text extraction is **client-side only** (PDF.js + mammoth.js from CDN) — raw files never leave the user's device.
- After updating the frontend and re-uploading to S3, invalidate the CloudFront cache: AWS Console → CloudFront → your distribution → Invalidations → Create invalidation → path `/*`.
