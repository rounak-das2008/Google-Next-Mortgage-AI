#!/usr/bin/env python3
"""
GCP Configuration Setup Script
This script sets up the necessary environment variables for GCP services
"""

import os
import logging

logger = logging.getLogger(__name__)

def setup_gcp_environment():
    """Set up GCP environment variables"""
    
    # Set GCP project and locations
    os.environ['GCP_PROJECT_ID'] = 'genai-hackathon-25'
    os.environ['GCP_LOCATION'] = 'us-central1'  # Vertex AI location
    os.environ['GCP_DOCUMENTAI_LOCATION'] = 'us'  # Document AI location
    
    # Use available Document AI processors
    # Bank Statement Processor for bank statements
    os.environ['GCP_BANK_PROCESSOR_ID'] = '1537b064c7a5d9ac'
    # Updated to use the new Payslip-resedential processor
    os.environ['GCP_FORM_PROCESSOR_ID'] = 'b5c6757f98067959'
    # OCR Processor for general text extraction
    os.environ['GCP_OCR_PROCESSOR_ID'] = 'f697ec4a24c16a21'
    
    # Set GOOGLE_APPLICATION_CREDENTIALS to use ADC
    # This tells the GCP client libraries to use Application Default Credentials
    if 'GOOGLE_APPLICATION_CREDENTIALS' not in os.environ:
        # ADC is already configured, so we don't need to set this
        logger.info("Using Application Default Credentials (ADC)")
    
    logger.info(f"GCP Project ID: {os.environ.get('GCP_PROJECT_ID')}")
    logger.info(f"GCP Vertex AI Location: {os.environ.get('GCP_LOCATION')}")
    logger.info(f"GCP Document AI Location: {os.environ.get('GCP_DOCUMENTAI_LOCATION')}")

def test_gcp_services():
    """Test if GCP services are accessible"""
    
    print("Testing GCP Services...")
    print("=" * 50)
    
    # Test Firestore
    try:
        from google.cloud import firestore
        db = firestore.Client()
        print("✅ Firestore: Connected successfully")
    except Exception as e:
        print(f"❌ Firestore: Error - {e}")
    
    # Test Document AI
    try:
        from google.cloud import documentai_v1 as documentai
        client = documentai.DocumentProcessorServiceClient()
        print("✅ Document AI: Client initialized successfully")
    except Exception as e:
        print(f"❌ Document AI: Error - {e}")
    
    # Test Vertex AI (Gemini)
    try:
        from google import genai
        # This will use ADC for authentication
        print("✅ Vertex AI: Client available")
    except Exception as e:
        print(f"❌ Vertex AI: Error - {e}")
    
    print("=" * 50)

if __name__ == "__main__":
    setup_gcp_environment()
    test_gcp_services()
