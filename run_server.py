"""
Unified server that runs both:
1. OneDrive watcher (detects files, extracts fields, creates sessions)
2. Flask API server (serves endpoints for frontend)

This allows the watcher and API to share the sessions dict in-memory.
"""

import os
import sys
import time
import uuid
import threading
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Import after loading env
from api_server import app, sessions, SessionData, CONFIG
from utils import extract_claim_fields, is_pdf_valid
from email_sender import load_email_metadata
from email_field_extractor import extract_email_fields
from onedrive_client_app import OneDriveClientApp


def watch_mode_api():
    """
    OneDrive watcher that extracts fields and creates sessions.
    Does NOT process claims - waits for API to trigger processing.
    """
    # OneDrive configuration
    tenant_id = os.getenv("ONEDRIVE_TENANT_ID")
    client_id = os.getenv("ONEDRIVE_CLIENT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
    user_email = os.getenv("ONEDRIVE_USER_EMAIL")
    folder_name = os.getenv("ONEDRIVE_FOLDER_NAME", "Input_attachments")
    
    if not all([tenant_id, client_id, client_secret, user_email]):
        print("✗ Error: Missing OneDrive credentials")
        return 1
    
    # Local folder for downloaded files
    input_folder = "input"
    os.makedirs(input_folder, exist_ok=True)
    
    # Initialize OneDrive client
    onedrive = OneDriveClientApp(tenant_id, client_id, client_secret, user_email, folder_name)
    
    print(f"[WATCHER] Monitoring OneDrive: {user_email}/{folder_name}")
    print(f"[WATCHER] Downloaded files saved to: {os.path.abspath(input_folder)}")
    
    # Track processed files to avoid duplicates - use file ID from OneDrive
    processed_file_ids = set()
    
    # Initial scan - mark existing files as processed
    if os.path.exists(input_folder):
        for filename in os.listdir(input_folder):
            if filename.lower().endswith('.pdf') or filename.lower().endswith('.pdf.json'):
                processed_file_ids.add(filename)  # Use filename as fallback for initial scan
    
    is_interactive = sys.stdout.isatty()
    
    iteration = 0
    while True:
        try:
            iteration += 1
            
            # List files from OneDrive
            onedrive_files = onedrive.list_files()
            
            # Check for RESET_CACHE.txt
            reset_file = next((f for f in onedrive_files if f['name'] == 'RESET_CACHE.txt'), None)
            if reset_file:
                print("\n[WATCHER] 🧹 RESET TRIGGERED")
                # Clear local input folder
                for filename in os.listdir(input_folder):
                    file_path = os.path.join(input_folder, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                    except Exception as e:
                        print(f"[WATCHER]   ✗ Could not delete {filename}: {e}")
                processed_file_ids.clear()
                sessions.clear()
                
                # Delete reset file from OneDrive
                try:
                    onedrive.delete_file(reset_file['id'])
                except:
                    pass
                continue
            
            # Filter for C*.pdf files and companion JSONs
            def is_target_file(filename):
                name_upper = filename.upper()
                name_lower = filename.lower()
                if not (name_upper.startswith('C') and len(filename) > 1 and filename[1].isdigit()):
                    return False, None
                if name_lower.endswith('.pdf'):
                    return True, 'pdf'
                elif name_lower.endswith('.pdf.json'):
                    return True, 'json'
                return False, None
            
            target_files = []
            for f in onedrive_files:
                is_target, file_type = is_target_file(f['name'])
                if is_target:
                    f['_file_type'] = file_type
                    target_files.append(f)
            
            # Separate PDFs and JSONs
            new_pdf_files = [f for f in target_files if f['_file_type'] == 'pdf']
            new_json_files = [f for f in target_files if f['_file_type'] == 'json']
            
            # Match PDF-JSON pairs
            pdf_json_pairs = []
            for pdf_file in new_pdf_files:
                pdf_name = pdf_file['name']
                pdf_id = pdf_file['id']
                json_name = pdf_name + ".json"
                
                # Skip if this PDF file ID was already processed
                if pdf_id in processed_file_ids:
                    continue
                
                # Skip if already has an ACTIVE (not completed) session
                # Allow re-processing if previous session is complete
                active_session_exists = any(
                    s.pdf_path and os.path.basename(s.pdf_path) == pdf_name and not s.processing_complete
                    for s in sessions.values()
                )
                if active_session_exists:
                    continue
                
                # Clean up old completed sessions for this file
                completed_sessions = [
                    sid for sid, s in sessions.items()
                    if s.pdf_path and os.path.basename(s.pdf_path) == pdf_name and s.processing_complete
                ]
                for sid in completed_sessions:
                    print(f"[WATCHER] 🧹 Cleaning up completed session for {pdf_name}: {sid[:8]}...")
                    sessions.pop(sid, None)
                
                # Check for companion JSON
                json_file = next((f for f in new_json_files if f['name'] == json_name), None)
                
                if json_file:
                    pdf_json_pairs.append({
                        'pdf': pdf_file,
                        'json': json_file,
                        'pdf_name': pdf_name,
                        'json_name': json_name
                    })
            
            # Status message
            active_sessions = sum(1 for s in sessions.values() if not s.processing_complete)
            total_sessions = len(sessions)
            status_msg = f"[WATCHER] [{datetime.now().strftime('%H:%M:%S')}] Check #{iteration}: {len(new_pdf_files)} PDFs, {len(pdf_json_pairs)} pairs ready, {active_sessions}/{total_sessions} active sessions"
            if is_interactive:
                print(status_msg, end='\r')
            elif iteration == 1 or iteration % 60 == 0 or pdf_json_pairs:
                print(status_msg)
            
            # Process new pairs - extract fields and create sessions
            for pair in pdf_json_pairs:
                pdf_file_info = pair['pdf']
                json_file_info = pair['json']
                pdf_filename = pair['pdf_name']
                json_filename = pair['json_name']
                
                print(f"\n[WATCHER] {'='*60}")
                print(f"[WATCHER] 📦 New file detected: {pdf_filename}")
                print(f"[WATCHER] {'='*60}")
                
                try:
                    # Download files
                    print(f"[WATCHER] 📥 Downloading files...")
                    json_path = onedrive.download_file(json_file_info, local_dir=input_folder)
                    print(f"[WATCHER]    ✓ JSON saved: {json_path}")
                    
                    pdf_path = onedrive.download_file(pdf_file_info, local_dir=input_folder)
                    print(f"[WATCHER]    ✓ PDF saved: {pdf_path}")
                    
                    # Validate PDF
                    print(f"[WATCHER] 📋 Validating PDF...")
                    is_valid, validation_reason = is_pdf_valid(pdf_path)
                    
                    if not is_valid:
                        print(f"[WATCHER] ⚠ Invalid PDF: {validation_reason}")
                        # Clean up and skip
                        if os.path.exists(pdf_path):
                            os.remove(pdf_path)
                        if os.path.exists(json_path):
                            os.remove(json_path)
                        continue
                    
                    print(f"[WATCHER]    ✓ PDF is valid")
                    
                    # Extract claim fields
                    print(f"[WATCHER] 📝 Extracting claim fields...")
                    claim_data = extract_claim_fields(pdf_path)
                    print(f"[WATCHER]    ✓ Extracted {len([v for v in claim_data.values() if v])} fields")
                    
                    # Load email metadata
                    print(f"[WATCHER] 📧 Loading email metadata...")
                    email_metadata = load_email_metadata(json_path)
                    if email_metadata:
                        print(f"[WATCHER]    ✓ Email metadata loaded")
                    else:
                        print(f"[WATCHER]    ⚠ No email metadata found")
                    
                    # Extract email fields using LLM
                    print(f"[WATCHER] 🤖 Extracting email fields with LLM...")
                    email_fields = None
                    if email_metadata:
                        try:
                            email_fields = extract_email_fields(email_metadata)
                            if email_fields:
                                print(f"[WATCHER]    ✓ Email fields extracted")
                                print(f"[WATCHER]       Sender: {email_fields.get('sender_name', 'N/A')}")
                                print(f"[WATCHER]       Receiver: {email_fields.get('receiver_name', 'N/A')}")
                                print(f"[WATCHER]       Policy: {email_fields.get('policy_number', 'N/A')}")
                        except Exception as e:
                            print(f"[WATCHER]    ⚠ Email field extraction failed: {str(e)}")
                            email_fields = None
                    
                    # Create session
                    session_id = str(uuid.uuid4())
                    session = SessionData(session_id)
                    session.pdf_path = pdf_path
                    session.json_path = json_path
                    session.claim_data = claim_data
                    session.email_metadata = email_metadata
                    session.email_fields = email_fields
                    session.onedrive_pdf_id = pdf_file_info['id']
                    session.onedrive_json_id = json_file_info['id']
                    
                    sessions[session_id] = session
                    
                    # Mark this PDF file ID as processed to prevent re-detection
                    processed_file_ids.add(pdf_file_info['id'])
                    print(f"[WATCHER] 📌 Marked file as processed: {pdf_file_info['id'][:20]}...")
                    
                    print(f"[WATCHER] ✓ Session created: {session_id[:8]}...")
                    print(f"[WATCHER] ⏳ Waiting for frontend to confirm via API")
                    print(f"[WATCHER] {'='*60}\n")
                    
                except Exception as e:
                    print(f"[WATCHER] ✗ Error processing {pdf_filename}: {str(e)}")
                    import traceback
                    traceback.print_exc()
            
        except Exception as e:
            print(f"\n[WATCHER] ✗ Error checking OneDrive: {str(e)}")
            print("[WATCHER]    Will retry in 5 seconds...")
        
        # Wait before next check
        time.sleep(5)


def run_flask_server():
    """Run the Flask API server"""
    port = int(os.getenv("API_PORT", 5000))
    print(f"[API] Starting Flask server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


def main():
    """Run both watcher and API server simultaneously"""
    print("\n" + "="*70)
    print("CLAIMS FRAUD UNIFIED SERVER")
    print("="*70)
    print("Starting both OneDrive watcher and API server...")
    print("="*70 + "\n")
    
    # Start Flask server in a separate thread
    api_thread = threading.Thread(target=run_flask_server, daemon=True)
    api_thread.start()
    
    # Give Flask a moment to start
    time.sleep(1)
    
    port = int(os.getenv("API_PORT", 5000))
    print(f"\n[API] Endpoints available at http://localhost:{port}")
    print(f"[API]   GET  /health")
    print(f"[API]   GET  /claims-api/pending")
    print(f"[API]   GET  /claims-api/pending/latest")
    print(f"[API]   POST /claims-api/email-fields")
    print(f"[API]   POST /claims-api/process")
    print(f"[API]   GET  /claims-api/output-pdf")
    print()
    
    # Run watcher in main thread (blocks until Ctrl+C)
    try:
        watch_mode_api()
    except KeyboardInterrupt:
        print("\n\n" + "="*70)
        print("UNIFIED SERVER STOPPED")
        print("="*70)
        
        # Clear input folder on shutdown
        from utils import clear_input_folder
        input_folder = CONFIG['INPUT_FOLDER']
        clear_input_folder(input_folder)
        
        print("Server shutdown complete.")
        print("="*70)


if __name__ == "__main__":
    main()
