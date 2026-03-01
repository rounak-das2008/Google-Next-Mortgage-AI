import os
import json
import logging
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory, send_file
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import uuid

# Set up GCP environment variables
os.environ['GCP_PROJECT_ID'] = 'genai-hackathon-25'
os.environ['GCP_LOCATION'] = 'us-central1'  # Vertex AI requires specific region
os.environ['GCP_DOCUMENTAI_LOCATION'] = 'us'  # Document AI uses 'us'
# Use available Document AI processors
os.environ['GCP_BANK_PROCESSOR_ID'] = '1537b064c7a5d9ac'
os.environ['GCP_FORM_PROCESSOR_ID'] = 'b5c6757f98067959'  # Updated to new Payslip-resedential processor
os.environ['GCP_OCR_PROCESSOR_ID'] = 'f697ec4a24c16a21'

from services.firestore_service import FirestoreService
from services.document_processor import DocumentProcessor
from services.validation_engine import ValidationEngine
from services.gemini_service import GeminiService
from services.auth_service import AuthService
from services.pdf_service import PDFService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None

csrf = CSRFProtect(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

firestore_service = FirestoreService()
document_processor = DocumentProcessor()
validation_engine = ValidationEngine()
gemini_service = GeminiService()
auth_service = AuthService()
pdf_service = PDFService()

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _sanitize_processed_documents(processed_docs):
    sanitized = []
    for doc in processed_docs or []:
        extracted_data = doc.get('extracted_data', {})
        if isinstance(extracted_data, dict):
            filtered_data = {k: v for k, v in extracted_data.items() if k not in ['raw_fields', 'text']}
        else:
            filtered_data = extracted_data
        sanitized.append({
            'filename': doc.get('filename'),
            'document_type': doc.get('document_type'),
            'extracted_data': filtered_data
        })
    return sanitized

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = auth_service.authenticate(username, password)
        
        if user:
            session.clear()
            session['username'] = user['username']
            session['role'] = user['role']
            session['user_id'] = user['user_id']
            session['name'] = user['name']
            session.permanent = False
            
            logger.info(f"User {username} logged in as {user['role']}")
            
            if user['role'] == 'broker':
                return redirect(url_for('broker_dashboard'))
            else:
                return redirect(url_for('assessor_dashboard'))
        else:
            flash('Invalid username or password. Please try again.')
            logger.warning(f"Failed login attempt for username: {username}")
    
    demo_creds = auth_service.get_demo_credentials()
    return render_template('login.html', demo_creds=demo_creds)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/broker/dashboard')
def broker_dashboard():
    if session.get('role') != 'broker':
        return redirect(url_for('login'))
    
    user_id = session.get('user_id', '')
    applications = firestore_service.get_applications_by_broker(user_id)
    
    return render_template('broker_dashboard.html', applications=applications)

@app.route('/broker/new-application', methods=['GET', 'POST'])
def new_application():
    if session.get('role') != 'broker':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        applicant_type = request.form.get('applicant_type')
        applicant_role = request.form.get('applicant_role')
        applicant_name = request.form.get('applicant_name')
        
        application_id = str(uuid.uuid4())
        application_data = {
            'application_id': application_id,
            'applicant_type': applicant_type,
            'applicant_role': applicant_role,
            'applicant_name': applicant_name,
            'broker_id': session.get('user_id'),
            'status': 'draft',
            'created_at': datetime.utcnow().isoformat(),
            'documents': [],
            'validation_results': None
        }
        
        firestore_service.create_application(application_data)
        session['current_application_id'] = application_id
        
        return redirect(url_for('upload_documents', application_id=application_id))
    
    return render_template('new_application.html')

@app.route('/broker/application/<application_id>/upload', methods=['GET', 'POST'])
def upload_documents(application_id):
    if session.get('role') != 'broker':
        return redirect(url_for('login'))
    
    application = firestore_service.get_application(application_id)
    if not application or application.get('broker_id') != session.get('user_id'):
        flash('Application not found or access denied')
        return redirect(url_for('broker_dashboard'))
    
    if request.method == 'POST':
        if 'documents' not in request.files:
            flash('No files uploaded')
            return redirect(request.url)
        
        files = request.files.getlist('documents')
        uploaded_docs = []
        
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{application_id}_{uuid.uuid4()}_{filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(filepath)
                
                uploaded_docs.append({
                    'filename': filename,
                    'stored_filename': unique_filename,
                    'filepath': filepath,
                    'uploaded_at': datetime.utcnow().isoformat()
                })
        
        if uploaded_docs:
            firestore_service.add_documents_to_application(application_id, uploaded_docs)
            return redirect(url_for('process_documents', application_id=application_id))
    
    return render_template('upload_documents.html', application=application)

@app.route('/broker/application/<application_id>/process')
def process_documents(application_id):
    if session.get('role') != 'broker':
        return redirect(url_for('login'))
    
    application = firestore_service.get_application(application_id)
    if not application:
        flash('Application not found')
        return redirect(url_for('broker_dashboard'))
    
    if application.get('broker_id') != session.get('user_id'):
        flash('Access denied - You do not own this application')
        return redirect(url_for('broker_dashboard'))
    
    return render_template('processing.html', application_id=application_id)

@app.route('/api/process/<application_id>', methods=['POST'])
def api_process_documents(application_id):
    if session.get('role') != 'broker':
        return jsonify({'error': 'Unauthorized - Broker access required'}), 403
    
    try:
        application = firestore_service.get_application(application_id)
        if not application:
            return jsonify({'error': 'Application not found'}), 404
        
        if application.get('broker_id') != session.get('user_id'):
            return jsonify({'error': 'Forbidden - You do not own this application'}), 403
        
        documents = application.get('documents', [])
        if not documents:
            return jsonify({'error': 'No documents to process'}), 400
        
        # Initialize processing status
        processing_status = {
            'status': 'processing',
            'started_at': datetime.utcnow().isoformat(),
            'total_documents': len(documents),
            'processed_documents': 0,
            'current_stage': 'initializing',
            'progress_percentage': 0
        }
        
        # Update application with initial processing status
        firestore_service.update_application_status(
            application_id, 
            'processing',
            processing_status=processing_status
        )
        
        # Start processing in a separate thread to avoid blocking
        from threading import Thread
        
        def process_documents_task():
            try:
                processed_docs = []
                total_docs = len(documents)
                
                for idx, doc in enumerate(documents):
                    try:
                        filepath = doc.get('filepath')
                        if not filepath or not os.path.exists(filepath):
                            logger.warning(f"Document file not found: {doc.get('filename')}")
                            continue
                        
                        # Update processing status
                        processing_status['current_stage'] = f"Classifying document {idx+1}/{total_docs}"
                        processing_status['progress_percentage'] = int((idx / total_docs) * 30)
                        firestore_service.update_application_processing_status(application_id, processing_status)
                        
                        # Extract raw text first to enable content-based classification
                        raw_text = ""
                        try:
                            # Use internal text extraction from document processor
                            raw_text = document_processor._extract_text_from_file(filepath)
                            logger.info(f"Extracted {len(raw_text)} characters from {doc.get('filename')} for classification")
                        except Exception as e:
                            logger.error(f"Failed to extract text for classification from {doc.get('filename')}: {e}")
                        
                        # Classify document using content
                        doc_type = gemini_service.classify_document(filepath, raw_text)
                        
                        # Update processing status
                        processing_status['current_stage'] = f"Extracting data from {doc_type}: {doc.get('filename')}"
                        processing_status['progress_percentage'] = int((idx / total_docs) * 30) + 10
                        firestore_service.update_application_processing_status(application_id, processing_status)
                        
                        # Extract data
                        extracted_data = document_processor.extract_document_data(filepath, doc_type)
                        
                        processed_docs.append({
                            'filename': doc.get('filename'),
                            'document_type': doc_type,
                            'extracted_data': extracted_data,
                            'filepath': filepath
                        })
                        
                        # Update processing status
                        processing_status['processed_documents'] = idx + 1
                        processing_status['progress_percentage'] = int((idx + 1) / total_docs * 60)
                        firestore_service.update_application_processing_status(application_id, processing_status)
                    
                    except Exception as doc_error:
                        logger.error(f"Error processing document {doc.get('filename')}: {str(doc_error)}", exc_info=True)
                        # Continue with next document instead of failing the entire process
                
                # Update processing status
                processing_status['current_stage'] = "Running validation engine"
                processing_status['progress_percentage'] = 70
                firestore_service.update_application_processing_status(application_id, processing_status)
                
                # Run validation
                validation_results = validation_engine.validate_application(processed_docs)
                
                # Update processing status
                processing_status['current_stage'] = "Generating AI summary"
                processing_status['progress_percentage'] = 90
                firestore_service.update_application_processing_status(application_id, processing_status)
                
                # Generate summary
                ai_summary = gemini_service.generate_application_summary(processed_docs, validation_results)
                
                # Update application with final results
                firestore_service.update_application_processing(
                    application_id,
                    processed_docs,
                    validation_results,
                    ai_summary
                )
                
                # Mark processing as complete
                processing_status['status'] = 'completed'
                processing_status['completed_at'] = datetime.utcnow().isoformat()
                processing_status['current_stage'] = "Processing complete"
                processing_status['progress_percentage'] = 100
                firestore_service.update_application_processing_status(application_id, processing_status)
                
            except Exception as e:
                logger.error(f"Error in processing thread: {str(e)}", exc_info=True)
                # Update status to indicate error
                processing_status['status'] = 'error'
                processing_status['error'] = str(e)
                processing_status['current_stage'] = "Error occurred"
                firestore_service.update_application_processing_status(application_id, processing_status)
        
        # Start processing thread
        processing_thread = Thread(target=process_documents_task)
        processing_thread.daemon = True
        processing_thread.start()
        
        return jsonify({
            'status': 'processing_started',
            'message': 'Document processing has started',
            'total_documents': len(documents)
        })
    
    except Exception as e:
        logger.error(f"Error initiating document processing: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/process/<application_id>/status', methods=['GET'])
def api_process_status(application_id):
    if session.get('role') != 'broker':
        return jsonify({'error': 'Unauthorized - Broker access required'}), 403
    
    try:
        application = firestore_service.get_application(application_id)
        if not application:
            return jsonify({'error': 'Application not found'}), 404
        
        if application.get('broker_id') != session.get('user_id'):
            return jsonify({'error': 'Forbidden - You do not own this application'}), 403
        
        processing_status = application.get('processing_status', {})
        
        return jsonify({
            'status': 'success',
            'processing_status': processing_status
        })
    
    except Exception as e:
        logger.error(f"Error getting processing status: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/broker/application/<application_id>/review')
def review_application(application_id):
    if session.get('role') != 'broker':
        return redirect(url_for('login'))
    
    application = firestore_service.get_application(application_id)
    if not application or application.get('broker_id') != session.get('user_id'):
        flash('Application not found or access denied')
        return redirect(url_for('broker_dashboard'))
    
    return render_template('review_application.html', application=application)

@app.route('/broker/application/<application_id>/submit', methods=['POST'])
def submit_application(application_id):
    if session.get('role') != 'broker':
        return jsonify({'error': 'Unauthorized - Broker access required'}), 403
    
    application = firestore_service.get_application(application_id)
    if not application:
        return jsonify({'error': 'Application not found'}), 404
    
    if application.get('broker_id') != session.get('user_id'):
        return jsonify({'error': 'Forbidden - You do not own this application'}), 403
    
    firestore_service.update_application_status(application_id, 'under_review')
    
    flash('Application submitted successfully!')
    return jsonify({'status': 'success', 'redirect': url_for('broker_dashboard')})

@app.route('/broker/application/<application_id>/delete', methods=['POST'])
def delete_application(application_id):
    if session.get('role') != 'broker':
        return jsonify({'error': 'Unauthorized - Broker access required'}), 403
    
    application = firestore_service.get_application(application_id)
    if not application:
        return jsonify({'error': 'Application not found'}), 404
        
    if application.get('broker_id') != session.get('user_id'):
        return jsonify({'error': 'Forbidden - You do not own this application'}), 403
        
    success = firestore_service.delete_application(application_id)
    if success:
        return jsonify({'status': 'success', 'message': 'Application deleted successfully'})
    else:
        return jsonify({'error': 'Failed to delete application'}), 500

@app.route('/assessor/dashboard')
def assessor_dashboard():
    if session.get('role') != 'assessor':
        return redirect(url_for('login'))
    
    status_filter = request.args.get('status', 'all')
    search_query = request.args.get('search', '')
    
    applications = firestore_service.get_all_applications(status_filter, search_query)
    
    return render_template('assessor_dashboard.html', 
                         applications=applications,
                         status_filter=status_filter,
                         search_query=search_query)

@app.route('/assessor/application/<application_id>')
def assessor_view_application(application_id):
    if session.get('role') != 'assessor':
        return redirect(url_for('login'))
    
    application = firestore_service.get_application(application_id)
    if not application:
        flash('Application not found')
        return redirect(url_for('assessor_dashboard'))
    
    return render_template('assessor_view.html', application=application)

@app.route('/assessor/application/<application_id>/update-status', methods=['POST'])
def update_application_status(application_id):
    if session.get('role') != 'assessor':
        return jsonify({'error': 'Unauthorized - Assessor access required'}), 403
    
    application = firestore_service.get_application(application_id)
    if not application:
        return jsonify({'error': 'Application not found'}), 404
    
    data = request.get_json()
    new_status = data.get('status')
    notes = data.get('notes', '')
    
    if new_status not in ['under_review', 'approved', 'rejected', 'pending_info']:
        return jsonify({'error': 'Invalid status'}), 400
    
    firestore_service.update_application_status(
        application_id, 
        new_status,
        assessor_id=session.get('user_id'),
        notes=notes
    )
    
    return jsonify({'status': 'success'})

@app.route('/application/<application_id>/download-summary')
def download_application_summary(application_id):
    if not session.get('role'):
        return redirect(url_for('login'))
    
    application = firestore_service.get_application(application_id)
    if not application:
        flash('Application not found')
        return redirect(request.referrer or url_for('index'))
    
    user_role = session.get('role')
    user_id = session.get('user_id')
    
    if user_role == 'broker' and application.get('broker_id') != user_id:
        flash('Access denied')
        return redirect(url_for('broker_dashboard'))
    
    if user_role not in ['broker', 'assessor']:
        flash('Unauthorized')
        return redirect(url_for('login'))
    
    sanitized_docs = _sanitize_processed_documents(application.get('processed_documents', []))
    uploaded_docs = [
        {
            'filename': doc.get('filename'),
            'uploaded_at': doc.get('uploaded_at')
        }
        for doc in application.get('documents', [])
    ]
    
    summary_payload = {
        'application_id': application_id,
        'applicant': {
            'name': application.get('applicant_name'),
            'type': application.get('applicant_type'),
            'role': application.get('applicant_role')
        },
        'status': application.get('status'),
        'ai_summary': application.get('ai_summary'),
        'validation_results': application.get('validation_results'),
        'uploaded_documents': uploaded_docs,
        'processed_documents': sanitized_docs,
        'generated_at': datetime.utcnow().isoformat()
    }
    
    json_bytes = json.dumps(summary_payload, indent=2, default=str).encode('utf-8')
    filename = f"{application_id}_summary.json"
    
    return send_file(
        BytesIO(json_bytes),
        mimetype='application/json',
        as_attachment=True,
        download_name=filename
    )

@app.route('/application/<application_id>/download-pdf')
def download_application_pdf(application_id):
    """Download application review summary as a professionally formatted PDF."""
    if not session.get('role'):
        return redirect(url_for('login'))
    
    application = firestore_service.get_application(application_id)
    if not application:
        flash('Application not found')
        return redirect(request.referrer or url_for('index'))
    
    user_role = session.get('role')
    user_id = session.get('user_id')
    
    if user_role == 'broker' and application.get('broker_id') != user_id:
        flash('Access denied')
        return redirect(url_for('broker_dashboard'))
    
    if user_role not in ['broker', 'assessor']:
        flash('Unauthorized')
        return redirect(url_for('login'))
    
    try:
        # Generate PDF
        pdf_bytes = pdf_service.generate_application_pdf(application)
        filename = f"{application_id[:8]}_review_summary.pdf"
        
        return send_file(
            BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}", exc_info=True)
        flash('Error generating PDF. Please try again.')
        return redirect(request.referrer or url_for('index'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if not session.get('role'):
        return jsonify({'error': 'Unauthorized - Login required'}), 403
    
    application_id = filename.split('_')[0] if '_' in filename else None
    if application_id:
        application = firestore_service.get_application(application_id)
        if application:
            user_role = session.get('role')
            user_id = session.get('user_id')
            
            if user_role == 'broker' and application.get('broker_id') != user_id:
                return jsonify({'error': 'Forbidden - Access denied'}), 403
    
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})

@app.context_processor
def inject_csrf_token():
    return {'csrf_token': generate_csrf}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
