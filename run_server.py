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
from api_server import app, sessions, SessionData, CONFIG, pending_frontend_data
from utils import extract_claim_fields, is_pdf_valid
from email_sender import load_email_metadata
from onedrive_client_app import OneDriveClientApp


def clear_input_folder(input_folder="input"):
    """Clear all files from the input folder"""
    if not os.path.exists(input_folder):
        print(f"[CLEANUP] Input folder does not exist: {input_folder}")
        return
    
    cleared_count = 0
    error_count = 0
    
    print(f"[CLEANUP] 🧹 Clearing input folder: {os.path.abspath(input_folder)}")
    
    for filename in os.listdir(input_folder):
        file_path = os.path.join(input_folder, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                cleared_count += 1
                print(f"[CLEANUP]   ✓ Deleted: {filename}")
        except Exception as e:
            error_count += 1
            print(f"[CLEANUP]   ✗ Could not delete {filename}: {e}")
    
    print(f"[CLEANUP] ✓ Cleared {cleared_count} file(s)")
    if error_count > 0:
        print(f"[CLEANUP] ✗ Failed to delete {error_count} file(s)")


def watch_mode_api():
    """
    OneDrive watcher that:
    1. Detects files in OneDrive
    2. Extracts claim data from PDF
    3. Loads email metadata from JSON
    4. Runs fraud detection analysis immediately
    5. Creates session with results
    6. Waits for frontend to call /process with policy number for report generation
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
                    
                    # Email fields will be extracted by frontend - no backend extraction
                    print(f"[WATCHER] ⏭  Email field extraction skipped (handled by frontend)")
                    email_fields = None
                    
                    # Run fraud detection immediately
                    print(f"[WATCHER] 🔍 Starting fraud detection analysis...")
                    from app import FraudDetectionSystem
                    fraud_system = FraudDetectionSystem(use_ai=True)
                    
                    print(f"[WATCHER]    Analyzing claim for fraud...")
                    fraud_results = fraud_system.analyze_claim(pdf_path)
                    
                    if "error" in fraud_results:
                        print(f"[WATCHER] ✗ Fraud detection failed: {fraud_results['error']}")
                        # Clean up and skip
                        if os.path.exists(pdf_path):
                            os.remove(pdf_path)
                        if os.path.exists(json_path):
                            os.remove(json_path)
                        continue
                    
                    risk_level = fraud_results.get('fraud_detection', {}).get('risk_level', 'Unknown')
                    flags_count = fraud_results.get('fraud_detection', {}).get('flags_count', 0)
                    print(f"[WATCHER]    ✓ Analysis complete - Risk: {risk_level}, Flags: {flags_count}")
                    
                    # Create session with fraud results
                    session_id = str(uuid.uuid4())
                    session = SessionData(session_id)
                    session.pdf_path = pdf_path
                    session.json_path = json_path
                    session.claim_data = claim_data
                    session.email_metadata = email_metadata
                    session.email_fields = email_fields
                    session.results = fraud_results  # Store fraud detection results
                    session.onedrive_pdf_id = pdf_file_info['id']
                    session.onedrive_json_id = json_file_info['id']
                    
                    sessions[session_id] = session
                    
                    # Mark this PDF file ID as processed to prevent re-detection
                    processed_file_ids.add(pdf_file_info['id'])
                    print(f"[WATCHER] 📌 Marked file as processed: {pdf_file_info['id'][:20]}...")
                    
                    print(f"[WATCHER] ✓ Session created: {session_id[:8]}...")
                    
                    # Check if frontend already sent data for this file
                    if pdf_filename in pending_frontend_data:
                        print(f"[WATCHER] 🎯 Found pending frontend data for {pdf_filename}")
                        frontend_data = pending_frontend_data[pdf_filename]
                        
                        if not frontend_data.get('processed', False):
                            print(f"[WATCHER] 📋 Processing with frontend data immediately...")
                            
                            # Store frontend data in session
                            session.confirmed_email_fields = frontend_data['email_fields']
                            
                            # Handle form PDF if provided
                            if frontend_data.get('form_pdf_base64'):
                                try:
                                    import base64
                                    pdf_bytes = base64.b64decode(frontend_data['form_pdf_base64'])
                                    form_pdf_filename = f"form_{pdf_filename.replace('.pdf', '')}.pdf"
                                    form_pdf_path = os.path.join(input_folder, form_pdf_filename)
                                    with open(form_pdf_path, 'wb') as f:
                                        f.write(pdf_bytes)
                                    session.form_pdf_path = form_pdf_path
                                    print(f"[WATCHER]    ✓ Form PDF saved")
                                except Exception as e:
                                    print(f"[WATCHER]    ⚠ Form PDF failed: {e}")
                            
                            # Trigger report generation immediately
                            try:
                                policy_number = frontend_data['email_fields'].get('policy_number')
                                print(f"[WATCHER]    Policy: {policy_number}")
                                
                                # Update fraud results with frontend policy number
                                if policy_number and 'claim_data' in fraud_results:
                                    fraud_results['claim_data']['policy_number'] = policy_number
                                    session.results = fraud_results
                                
                                # Generate reports
                                fraud_system.generate_report(fraud_results, output_format="console")
                                
                                # Create claims folder
                                claims_folder_path = None
                                if policy_number and fraud_system.onedrive_client:
                                    claim_subfolder_name = f"CN_{policy_number}"
                                    claims_fraud_folder = fraud_system.onedrive_claims_fraud_folder
                                    folder_id, claims_folder_path = fraud_system.onedrive_client.create_subfolder(
                                        claims_fraud_folder, claim_subfolder_name
                                    )
                                    session.claims_folder_path = claims_folder_path
                                    print(f"[WATCHER]    ✓ Folder: {claims_folder_path}")
                                
                                # Save results
                                output_paths = fraud_system.save_results(
                                    fraud_results,
                                    email_metadata=email_metadata,
                                    input_pdf_path=pdf_path,
                                    claims_folder_path=claims_folder_path,
                                    confirmed_policy_number=policy_number
                                )
                                
                                if output_paths and len(output_paths) >= 3:
                                    session.output_pdf_path = output_paths[2]
                                    
                                    # Get OneDrive URLs
                                    if fraud_system.onedrive_client and claims_folder_path:
                                        try:
                                            folder_info = fraud_system.onedrive_client.get_subfolder_info(claims_folder_path)
                                            if folder_info and folder_info.get('web_url'):
                                                session.claims_folder_url = folder_info['web_url']
                                                session.output_pdf_url = folder_info['web_url']
                                        except Exception as e:
                                            print(f"[WATCHER]    ⚠ URL error: {e}")
                                
                                # Upload form PDF if present - DISABLED
                                # if session.form_pdf_path and fraud_system.onedrive_client and claims_folder_path:
                                #     try:
                                #         import requests
                                #         upload_url = f"https://graph.microsoft.com/v1.0/users/{fraud_system.onedrive_client.user_email}/drive/root:/{claims_folder_path}/form_response.pdf:/content"
                                #         with open(session.form_pdf_path, 'rb') as f:
                                #             headers = fraud_system.onedrive_client._get_headers()
                                #             headers["Content-Type"] = "application/octet-stream"
                                #             response = requests.put(upload_url, headers=headers, data=f.read())
                                #             if response.status_code in [200, 201]:
                                #                 print(f"[WATCHER]    ✓ Form PDF uploaded")
                                #     except Exception as e:
                                #         print(f"[WATCHER]    ⚠ Form upload failed: {e}")
                                
                                session.processing_complete = True
                                
                                # Save to database
                                try:
                                    from api_server import insert_claim
                                    claim_db_data = fraud_results.get('claim_data', {})
                                    
                                    # Ensure policy_number is mapped to policy_id for database
                                    if 'policy_number' in claim_db_data and not claim_db_data.get('policy_id'):
                                        claim_db_data['policy_id'] = claim_db_data['policy_number']
                                    
                                    # Use loss description from claim form for claim description
                                    if not claim_db_data.get('claim_description'):
                                        claim_db_data['claim_description'] = claim_db_data.get('loss_description', '')
                                    
                                    # Handle "Same as Reporter" logic - copy insured data to reporting if reporting is empty
                                    insured_same = claim_db_data.get('insured_same_as_reporter', False)
                                    if insured_same:
                                        # Copy insured fields to reporting fields if reporting fields are empty
                                        if not claim_db_data.get('reporting_first_name'):
                                            claim_db_data['reporting_first_name'] = claim_db_data.get('insured_first_name', '')
                                        if not claim_db_data.get('reporting_last_name'):
                                            claim_db_data['reporting_last_name'] = claim_db_data.get('insured_last_name', '')
                                        if not claim_db_data.get('reporting_address'):
                                            claim_db_data['reporting_address'] = claim_db_data.get('insured_address', '')
                                        if not claim_db_data.get('reporting_city'):
                                            claim_db_data['reporting_city'] = claim_db_data.get('insured_city', '')
                                        if not claim_db_data.get('reporting_state'):
                                            claim_db_data['reporting_state'] = claim_db_data.get('insured_state', '')
                                        if not claim_db_data.get('reporting_zip'):
                                            claim_db_data['reporting_zip'] = claim_db_data.get('insured_zip', '')
                                        if not claim_db_data.get('reporting_email'):
                                            claim_db_data['reporting_email'] = claim_db_data.get('insured_email', '')
                                        if not claim_db_data.get('reporting_phone'):
                                            claim_db_data['reporting_phone'] = claim_db_data.get('insured_phone', '')
                                    
                                    claim_db_data['folder_url'] = session.claims_folder_url
                                    claim_db_data['claim_status'] = 'Submitted'
                                    db_claim_id = insert_claim(claim_db_data)
                                    print(f"[WATCHER]    ✓ Saved to DB: {db_claim_id}")
                                except Exception as e:
                                    print(f"[WATCHER]    ⚠ DB save failed: {e}")
                                
                                print(f"[WATCHER] ✓ Processing complete with frontend data!")
                                
                                # Mark as processed
                                frontend_data['processed'] = True
                                
                            except Exception as e:
                                print(f"[WATCHER]    ✗ Report generation failed: {e}")
                                import traceback
                                traceback.print_exc()
                        else:
                            print(f"[WATCHER] ℹ Frontend data already processed")
                    else:
                        print(f"[WATCHER] ⏳ Waiting for frontend to call /process with policy number")
                    
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
    port = int(os.getenv("API_PORT", 5006))
    print(f"[API] Starting Flask server on port {port}...")
    # Bind to 127.0.0.1 for maximum compatibility with ngrok
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)


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
    
    port = int(os.getenv("API_PORT", 5006))
    print(f"\n[API] Endpoints available at http://localhost:{port}")
    print(f"[API]   GET  /health")
    print(f"[API]   POST /claims-api/process           (Primary: accepts email_fields)")
    print(f"[API]   GET  /claims-api/pending           (Optional: list pending files)")
    print(f"[API]   POST /claims-api/email-fields      (Legacy: use /process instead)")
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
        print()
        clear_input_folder()
        print()


if __name__ == "__main__":
    main()
