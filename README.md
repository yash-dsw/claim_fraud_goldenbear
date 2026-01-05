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

Run the main app with a claim PDF path:

```bash
python app.py C1_JohnDoe_Jetwire.pdf
```

Reports (JSON + HTML) are written to the `output/` directory.

## Requirements

Required packages are listed in `requirements.txt`.