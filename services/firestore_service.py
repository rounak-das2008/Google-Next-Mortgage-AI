import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

try:
    from google.cloud import firestore
    FIRESTORE_AVAILABLE = True
except Exception as e:
    logger.warning(f"Firestore not available: {e}. Using in-memory storage.")
    FIRESTORE_AVAILABLE = False

class FirestoreService:
    def __init__(self):
        self.in_memory_db = {}
        
        # Use FIRESTORE_DATABASE env var or default to "mortgage"
        firestore_db = os.getenv('FIRESTORE_DATABASE', 'mortgage')
        firestore_project = os.getenv('FIRESTORE_PROJECT','gebu-demo-sandbox')  # optional override
        
        if FIRESTORE_AVAILABLE:
            try:
                # Initialize client against the specified Firestore database
                if firestore_project:
                    self.db = firestore.Client(project=firestore_project, database=firestore_db)
                else:
                    self.db = firestore.Client(database=firestore_db)
                self.use_firestore = True
                logger.info(f"Firestore initialized successfully (database={firestore_db}, project={firestore_project or 'default'})")
            except Exception as e:
                logger.warning(f"Could not initialize Firestore: {e}. Using in-memory storage.")
                self.use_firestore = False
        else:
            self.use_firestore = False
            logger.info("Using in-memory storage (Firestore not available)")
    
    def create_application(self, application_data: Dict[str, Any]) -> str:
        application_id = application_data['application_id']
        
        if self.use_firestore:
            try:
                self.db.collection('applications').document(application_id).set(application_data)
                logger.info(f"Created application {application_id} in Firestore")
            except Exception as e:
                logger.error(f"Error creating application in Firestore: {e}")
                self.in_memory_db[application_id] = application_data
        else:
            self.in_memory_db[application_id] = application_data
        
        return application_id
    
    def get_application(self, application_id: str) -> Optional[Dict[str, Any]]:
        if self.use_firestore:
            try:
                doc = self.db.collection('applications').document(application_id).get()
                if doc.exists:
                    return doc.to_dict()
            except Exception as e:
                logger.error(f"Error getting application from Firestore: {e}")
        
        return self.in_memory_db.get(application_id)
    
    def get_applications_by_broker(self, broker_id: str) -> List[Dict[str, Any]]:
        applications = []
        
        if self.use_firestore:
            try:
                docs = self.db.collection('applications').where('broker_id', '==', broker_id).stream()
                applications = [doc.to_dict() for doc in docs]
                return sorted(applications, key=lambda x: x.get('created_at', ''), reverse=True)
            except Exception as e:
                logger.error(f"Error getting broker applications from Firestore: {e}")
        
        applications = [app for app in self.in_memory_db.values() if app.get('broker_id') == broker_id]
        return sorted(applications, key=lambda x: x.get('created_at', ''), reverse=True)
    
    def get_all_applications(self, status_filter: str = 'all', search_query: str = '') -> List[Dict[str, Any]]:
        applications = []
        
        if self.use_firestore:
            try:
                query = self.db.collection('applications')
                
                if status_filter != 'all':
                    query = query.where('status', '==', status_filter)
                
                docs = query.stream()
                applications = [doc.to_dict() for doc in docs]
            except Exception as e:
                logger.error(f"Error getting all applications from Firestore: {e}")
                applications = list(self.in_memory_db.values())
        else:
            applications = list(self.in_memory_db.values())
        
        if status_filter != 'all':
            applications = [app for app in applications if app.get('status') == status_filter]
        
        if search_query:
            applications = [
                app for app in applications 
                if search_query.lower() in app.get('application_id', '').lower() or
                   search_query.lower() in app.get('applicant_name', '').lower()
            ]
        
        return sorted(applications, key=lambda x: x.get('created_at', ''), reverse=True)
    
    def add_documents_to_application(self, application_id: str, documents: List[Dict[str, Any]]) -> None:
        if self.use_firestore:
            try:
                doc_ref = self.db.collection('applications').document(application_id)
                doc = doc_ref.get()
                
                if doc.exists:
                    current_docs = doc.to_dict().get('documents', [])
                    current_docs.extend(documents)
                    doc_ref.update({'documents': current_docs})
                    logger.info(f"Added {len(documents)} documents to application {application_id}")
                    return
            except Exception as e:
                logger.error(f"Error adding documents to Firestore: {e}")
        
        if application_id in self.in_memory_db:
            current_docs = self.in_memory_db[application_id].get('documents', [])
            current_docs.extend(documents)
            self.in_memory_db[application_id]['documents'] = current_docs
    
    def update_application_processing(self, application_id: str, processed_docs: List[Dict[str, Any]], 
                                     validation_results: Dict[str, Any], ai_summary: str) -> None:
        update_data = {
            'processed_documents': processed_docs,
            'validation_results': validation_results,
            'ai_summary': ai_summary,
            'processed_at': datetime.utcnow().isoformat(),
            'status': 'processed'
        }
        
        if self.use_firestore:
            try:
                self.db.collection('applications').document(application_id).update(update_data)
                logger.info(f"Updated processing data for application {application_id}")
                return
            except Exception as e:
                logger.error(f"Error updating application in Firestore: {e}")
        
        if application_id in self.in_memory_db:
            self.in_memory_db[application_id].update(update_data)
    
    def update_application_status(self, application_id: str, status: str, 
                                 assessor_id: Optional[str] = None, notes: str = '', processing_status: Optional[str] = None) -> None:
        update_data = {
            'status': status,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        if assessor_id:
            update_data['assessor_id'] = assessor_id
        
        if notes:
            update_data['assessor_notes'] = notes
            
        if processing_status:
            update_data['processing_status'] = processing_status
        
        if self.use_firestore:
            try:
                self.db.collection('applications').document(application_id).update(update_data)
                logger.info(f"Updated status for application {application_id} to {status}")
                return
            except Exception as e:
                logger.error(f"Error updating status in Firestore: {e}")
        
        if application_id in self.in_memory_db:
            self.in_memory_db[application_id].update(update_data)
            
    def update_application_processing_status(self, application_id: str, processing_status: str) -> None:
        """Update just the processing status of an application"""
        update_data = {
            'processing_status': processing_status,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        if self.use_firestore:
            try:
                self.db.collection('applications').document(application_id).update(update_data)
                logger.info(f"Updated processing status for application {application_id} to {processing_status}")
                return
            except Exception as e:
                logger.error(f"Error updating processing status in Firestore: {e}")
        
        if application_id in self.in_memory_db:
            self.in_memory_db[application_id].update(update_data)

    def delete_application(self, application_id: str) -> bool:
        """Deletes an application from Firestore or in-memory DB."""
        success = False
        if self.use_firestore:
            try:
                self.db.collection('applications').document(application_id).delete()
                logger.info(f"Deleted application {application_id} from Firestore")
                success = True
            except Exception as e:
                logger.error(f"Error deleting application {application_id} from Firestore: {e}")
        
        if application_id in self.in_memory_db:
            del self.in_memory_db[application_id]
            success = True
            
        return success
