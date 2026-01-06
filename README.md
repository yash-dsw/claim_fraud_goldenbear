# Claims Fraud Detection System

## Overview

Hybrid fraud-detection tool that:
- Extracts fields from ACORD claim PDFs
- Matches claims to existing policies
- Runs rule-based fraud detection
- Generates JSON and HTML reports
- Calls an AI agent when `OPENROUTER_API_KEY` is set

## Project structure

```
app.py
agent.py
extract_pdf_fields.py
policy_db.py
prompts.py
rules.py
utils.py
output/            # generated reports
acord_*.pdf        # pre-loaded policy forms
C*_*.pdf           # sample claim forms
requirements.txt
README.md
```

## Installation

1. Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure AI API key (optional):

```bash
cp .env.template .env
# Edit .env and set OPENROUTER_API_KEY if you want AI summaries
```

## Usage

### Local Processing

Run the main app with a claim PDF path:

```bash
python app.py C1_JohnDoe_Jetwire.pdf
```

Reports (JSON + HTML) are written to the `output/` directory.

### OneDrive Integration

The system can automatically download claims from OneDrive and upload HTML reports back to OneDrive.

**Setup:**

1. Enable OneDrive in your `.env` file:
```bash
ONEDRIVE_ENABLED=1
ONEDRIVE_TENANT_ID=your-tenant-id
ONEDRIVE_CLIENT_ID=your-client-id
ONEDRIVE_CLIENT_SECRET=your-client-secret
ONEDRIVE_USER_EMAIL=your-email@domain.com
ONEDRIVE_FOLDER_NAME=Input_attachments
ONEDRIVE_OUTPUT_FOLDER=Output_reports
```

2. Create folders in OneDrive:
   - `Input_attachments` - For claim PDFs to process
   - `Output_reports` - For HTML fraud reports (auto-created)

3. Run with OneDrive enabled:
```bash
python app.py
```

The system will:
- Download PDF claims from `Input_attachments` folder
- Process each claim for fraud detection
- Save reports locally to `output/` directory
- **Upload HTML reports to `Output_reports` OneDrive folder**

### Watch Mode

Continuously monitor OneDrive for new claims:

```bash
python app.py --watch
```

The system will automatically process new claims as they appear in the OneDrive folder.

## Requirements

Required packages are listed in `requirements.txt`.