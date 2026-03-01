import logging
import os
import re
from datetime import datetime
from typing import Dict, Any, Optional, List
from decimal import Decimal
import PyPDF2
from PIL import Image

logger = logging.getLogger(__name__)

try:
    from google.cloud import documentai_v1 as documentai
    DOCUMENTAI_AVAILABLE = True
except Exception as e:
    logger.warning(f"Document AI not available: {e}. Using fallback extraction.")
    DOCUMENTAI_AVAILABLE = False

class DocumentProcessor:
    def __init__(self):
        self.use_document_ai = False
        
        if DOCUMENTAI_AVAILABLE:
            try:
                project_id = os.environ.get('GCP_PROJECT_ID')
                # Document AI uses 'us' location, separate from Vertex AI location
                location = os.environ.get('GCP_DOCUMENTAI_LOCATION', os.environ.get('GCP_LOCATION', 'us'))
                
                # Get specific processor IDs
                self.bank_processor_id = os.environ.get('GCP_BANK_PROCESSOR_ID')
                self.form_processor_id = os.environ.get('GCP_FORM_PROCESSOR_ID')
                self.ocr_processor_id = os.environ.get('GCP_OCR_PROCESSOR_ID')
                
                if project_id and (self.bank_processor_id or self.form_processor_id or self.ocr_processor_id):
                    self.client = documentai.DocumentProcessorServiceClient()
                    self.project_id = project_id
                    self.location = location
                    self.use_document_ai = True
                    logger.info(f"Document AI initialized successfully with specific processors (location: {location})")
                else:
                    logger.info("GCP credentials not configured. Using fallback extraction.")
            except Exception as e:
                logger.warning(f"Could not initialize Document AI: {e}. Using fallback extraction.")
        else:
            logger.info("Using fallback document extraction (Document AI not available)")
    
    def extract_document_data(self, filepath: str, doc_type: str) -> Dict[str, Any]:
        if self.use_document_ai:
            try:
                return self._extract_with_documentai(filepath, doc_type)
            except Exception as e:
                logger.error(f"Error with Document AI extraction: {e}. Falling back to text extraction.")
        
        try:
            return self._extract_with_fallback(filepath, doc_type)
        except Exception as fallback_err:
            logger.error(f"Fallback extraction failed: {fallback_err}")
            # Return empty data structure with error information
            return {
                'document_type': doc_type,
                'confidence': 0.0,
                'fields': {},
                'error': str(fallback_err),
                'extraction_status': 'failed'
            }
    
    def _extract_with_documentai(self, filepath: str, doc_type: str) -> Dict[str, Any]:
        with open(filepath, "rb") as f:
            file_content = f.read()
        
        mime_type = "application/pdf"
        if filepath.lower().endswith(('.png', '.jpg', '.jpeg')):
            mime_type = "image/jpeg"
        
        # Choose the appropriate processor based on document type
        processor_id = None
        if doc_type == 'bank_statement' and self.bank_processor_id:
            processor_id = self.bank_processor_id
        elif doc_type == 'payslip' and self.form_processor_id:
            processor_id = self.form_processor_id
        elif self.ocr_processor_id:
            processor_id = self.ocr_processor_id
        
        if not processor_id:
            logger.warning(f"No suitable processor found for {doc_type}, using fallback")
            return self._extract_with_fallback(filepath, doc_type)
        
        processor_name = f"projects/{self.project_id}/locations/{self.location}/processors/{processor_id}"
        
        raw_document = documentai.RawDocument(content=file_content, mime_type=mime_type)
        request = documentai.ProcessRequest(name=processor_name, raw_document=raw_document)
        
        result = self.client.process_document(request=request)
        document = result.document
        
        extracted_data = {
            'text': document.text,
            'confidence': 0.0,
            'fields': {}
        }
        
        # Extract entities if available - handle both single values and arrays
        # Group entities by type to handle multiple occurrences
        entity_groups = {}
        
        for entity in document.entities:
            field_name = entity.type_
            field_value = entity.mention_text
            confidence = entity.confidence
            
            # For table items that can have multiple occurrences, collect them in arrays
            if field_name in ['earning_item', 'deduction_item', 'superannuation_item', 'tax_item']:
                if field_name not in entity_groups:
                    entity_groups[field_name] = []
                
                # Extract properties (subfields) for this entity
                item_data = {
                    'value': field_value,
                    'confidence': confidence
                }
                
                # Extract subfields from entity properties
                if hasattr(entity, 'properties') and entity.properties:
                    for prop in entity.properties:
                        prop_name = prop.type_
                        prop_value = prop.mention_text if hasattr(prop, 'mention_text') else None
                        if prop_value:
                            item_data[prop_name] = prop_value
                
                entity_groups[field_name].append(item_data)
            else:
                # Single value fields
                extracted_data['fields'][field_name] = {
                    'value': field_value,
                    'confidence': confidence
                }
            
            if confidence > extracted_data['confidence']:
                extracted_data['confidence'] = confidence
        
        # Add grouped table items to fields
        for field_name, items in entity_groups.items():
            extracted_data['fields'][field_name] = items
        
        # Also extract individual subfields that might be standalone
        for entity in document.entities:
            # Check if this is a subfield (like earning_type, earning_this_period, etc.)
            field_name = entity.type_
            if field_name not in extracted_data['fields'] and field_name not in entity_groups:
                # Check if it's a subfield that should be grouped
                if any(field_name.startswith(prefix) for prefix in ['earning_', 'deduction_', 'superannuation_', 'tax_']):
                    # Store as individual field but will be grouped in parsing
                    extracted_data['fields'][field_name] = {
                        'value': entity.mention_text,
                        'confidence': entity.confidence
                    }
        
        # Parse based on document type
        if doc_type == 'payslip':
            return self._parse_payslip_fields(extracted_data)
        elif doc_type == 'bank_statement':
            return self._parse_bank_statement_fields(extracted_data)
        
        return extracted_data
    
    def _extract_with_fallback(self, filepath: str, doc_type: str) -> Dict[str, Any]:
        text = self._extract_text_from_file(filepath)
        
        if doc_type == 'payslip':
            return self._parse_payslip_from_text(text)
        elif doc_type == 'bank_statement':
            return self._parse_bank_statement_from_text(text)
        
        return {'text': text, 'confidence': 0.5, 'fields': {}}
    
    def _extract_text_from_file(self, filepath: str) -> str:
        try:
            if filepath.lower().endswith('.pdf'):
                with open(filepath, 'rb') as f:
                    try:
                        reader = PyPDF2.PdfReader(f)
                        text_parts = []
                        for page_num, page in enumerate(reader.pages):
                            try:
                                page_text = page.extract_text()
                                if page_text:
                                    text_parts.append(page_text)
                            except Exception as page_error:
                                logger.warning(f"Error extracting text from page {page_num + 1} of {filepath}: {page_error}")
                                continue
                        return "\n".join(text_parts) if text_parts else ""
                    except Exception as pdf_error:
                        logger.error(f"Error reading PDF {filepath}: {pdf_error}")
                        # Try alternative PDF reading method
                        try:
                            import fitz  # PyMuPDF
                            doc = fitz.open(filepath)
                            text_parts = []
                            for page in doc:
                                text_parts.append(page.get_text())
                            doc.close()
                            return "\n".join(text_parts)
                        except ImportError:
                            logger.warning("PyMuPDF not available for PDF fallback")
                        except Exception as fitz_error:
                            logger.error(f"PyMuPDF fallback also failed for {filepath}: {fitz_error}")
                        return ""
            else:
                return f"[Image file: {os.path.basename(filepath)}]"
        except Exception as e:
            logger.error(f"Error extracting text from {filepath}: {e}")
            return ""
    
    def _parse_payslip_from_text(self, text: str) -> Dict[str, Any]:
        try:
            # Normalize text for better extraction
            normalized_text = ' '.join(text.replace('\n', ' ').split())
            
            # Try multiple patterns for each field to improve extraction
            data = {
                'document_type': 'payslip',
                'confidence': 0.6,
                'employee_name': (
                    self._extract_pattern(text, r'Employee[:\s]+([A-Z][a-z]+\s+[A-Z][a-z]+)', None) or
                    self._extract_pattern(text, r'Name[:\s]+([A-Z][a-z]+\s+[A-Z][a-z]+)', None) or
                    self._extract_pattern(text, r'Employee\s*Name[:\s]+([A-Za-z\s]+)', None) or
                    self._extract_pattern(text, r'(?:EMPLOYEE|Employee)[\s:]+([A-Za-z\s]+?)(?:\s{2,}|\n)', 'Unknown') or
                    self._extract_pattern(normalized_text, r'employee\s*(?:name)?[\s:]*([A-Za-z\s]+?)(?:\s{2,}|$)', 'Unknown')
                ),
                'employer_name': (
                    self._extract_pattern(text, r'Employer[:\s]+([A-Z][\w\s&\.]+(?:PTY LTD|Ltd|LIMITED|Inc|LLC)?)', None) or
                    self._extract_pattern(text, r'Company[:\s]+([A-Z][\w\s&\.]+(?:PTY LTD|Ltd|LIMITED|Inc|LLC)?)', None) or
                    self._extract_pattern(text, r'(?:EMPLOYER|Employer|COMPANY|Company)[\s:]+([A-Za-z0-9\s&\.]+?)(?:\s{2,}|\n)', 'Unknown') or
                    self._extract_pattern(normalized_text, r'employer\s*(?:name)?[\s:]*([A-Za-z\s&\.]+?)(?:\s{2,}|$)', 'Unknown')
                ),
                'abn': (
                    self._extract_pattern(text, r'ABN[:\s]+([\d\s-]{11,14})', None) or
                    self._extract_pattern(text, r'A\.B\.N\.?[:\s]+([\d\s-]{11,14})', None) or
                    self._extract_pattern(text, r'(?:ABN|A\.B\.N\.|Tax File Number)[\s:]+([0-9\s-]{9,14})', None) or
                    self._extract_pattern(normalized_text, r'abn\s*(?:number)?[\s:]*([0-9\s-]{11,14})', None)
                ),
                'pay_period_start': (
                    self._extract_date(text, r'Pay Period[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})') or
                    self._extract_date(text, r'Period[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})') or
                    self._extract_date(text, r'(?:PAY PERIOD|Pay Period|Period)[\s:]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})') or
                    self._extract_date(text, r'(?:From|Start)[\s:]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})')
                ),
                'pay_period_end': (
                    self._extract_date(text, r'to[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})') or
                    self._extract_date(text, r'(?:to|TO|To|-)[\s:]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})') or
                    self._extract_date(text, r'(?:End|Through)[\s:]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})')
                ),
                'pay_date': (
                    self._extract_date(text, r'Pay Date[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})') or
                    self._extract_date(text, r'Date[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})') or
                    self._extract_date(text, r'(?:PAY DATE|Pay Date|Payment Date|Date Paid)[\s:]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})') or
                    self._extract_date(normalized_text, r'pay\s*date[\s:]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})')
                ),
                'gross_pay': (
                    self._extract_currency(text, r'Gross Pay[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'Gross[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:GROSS PAY|Gross Pay|Total Gross)[\s:]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(normalized_text, r'gross\s*(?:pay)?[\s:]*\$?([\d,]+\.?\d*)')
                ),
                'net_pay': (
                    self._extract_currency(text, r'Net Pay[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'Net[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:NET PAY|Net Pay|Take Home|Net Amount)[\s:]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(normalized_text, r'net\s*(?:pay)?[\s:]*\$?([\d,]+\.?\d*)')
                ),
                'ytd_gross': (
                    self._extract_currency(text, r'YTD Gross[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'Year to Date[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:YTD|Year to Date|YTD Gross)[\s:]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(normalized_text, r'ytd\s*(?:gross)?[\s:]*\$?([\d,]+\.?\d*)')
                ),
                'tax_withheld': (
                    self._extract_currency(text, r'Tax[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'PAYG[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:TAX|Tax|PAYG|Withholding|Income Tax)[\s:]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(normalized_text, r'tax\s*(?:withheld)?[\s:]*\$?([\d,]+\.?\d*)')
                ),
                'superannuation': (
                    self._extract_currency(text, r'Super[annuation]*[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:SUPER|Super|Superannuation|SGC)[\s:]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(normalized_text, r'super(?:annuation)?[\s:]*\$?([\d,]+\.?\d*)')
                ),
                'overtime': (
                    self._extract_currency(text, r'Overtime[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:OVERTIME|Overtime|OT)[\s:]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(normalized_text, r'overtime[\s:]*\$?([\d,]+\.?\d*)')
                ),
                'allowances': (
                    self._extract_currency(text, r'Allowance[s]*[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:ALLOWANCE|Allowances|Allowance)[\s:]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(normalized_text, r'allowance[s]*[\s:]*\$?([\d,]+\.?\d*)')
                ),
                'raw_text': text[:1000]  # Increased to capture more context
            }
            
            # Extract earning items from text (commission, overtime, allowances, etc.)
            data['earning_items'] = self._extract_earning_items(text)
            
            # Extract deduction items from text
            data['deduction_items'] = self._extract_deduction_items(text)
            
            return data
        except Exception as e:
            logger.error(f"Error parsing payslip from text: {e}")
            return {
                'document_type': 'payslip',
                'confidence': 0.1,
                'error': str(e),
                'extraction_status': 'failed',
                'raw_text': text[:100] if text else ""
            }
    
    def _parse_bank_statement_from_text(self, text: str) -> Dict[str, Any]:
        try:
            # Normalize text for better extraction
            normalized_text = ' '.join(text.replace('\n', ' ').split())
            
            # Try multiple patterns for each field to improve extraction
            data = {
                'document_type': 'bank_statement',
                'confidence': 0.6,
                'account_holder': (
                    self._extract_pattern(text, r'Account Holder[:\s]+([A-Za-z\s]+)', None) or
                    self._extract_pattern(text, r'Name[:\s]+([A-Za-z\s]+)', None) or
                    self._extract_pattern(text, r'(?:ACCOUNT HOLDER|Account Holder|Customer|Name)[\s:]+([A-Za-z\s]+?)(?:\s{2,}|\n)', 'Unknown')
                ),
                'account_number': (
                    self._extract_pattern(text, r'Account[:\s]+([\d\s-]{6,20})', None) or
                    self._extract_pattern(text, r'Account Number[:\s]+([\d\s-]{6,20})', None) or
                    self._extract_pattern(text, r'(?:ACCOUNT|Account|A/C)(?:\s*No\.?|\s*Number)?[\s:]+([0-9\s-]{6,20})', None)
                ),
                'bank_name': (
                    self._extract_pattern(text, r'Bank[:\s]+([A-Za-z\s&]+)', None) or
                    self._extract_pattern(text, r'(?:BANK|Bank)[\s:]+([A-Za-z\s&]+?)(?:\s{2,}|\n)', None)
                ),
                'bsb': (
                    self._extract_pattern(text, r'BSB[:\s]+([\d-]{6,8})', None) or
                    self._extract_pattern(text, r'(?:BSB|Branch)[\s:]+([0-9-]{6,8})', None)
                ),
                'statement_date_range': (
                    self._extract_pattern(text, r'Statement Period[:\s]+([A-Za-z0-9\s,/-]+)', None) or
                    self._extract_pattern(text, r'Period[:\s]+([A-Za-z0-9\s,/-]+)', None)
                ),
                'statement_period_start': (
                    self._extract_date(text, r'Period[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})') or
                    self._extract_date(text, r'Statement Period[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})') or
                    self._extract_date(text, r'(?:PERIOD|Period|Statement Period|From)[\s:]+(\d{1,2}[/-\.]\d{1,2}[/-\.]\d{2,4})')
                ),
                'statement_period_end': (
                    self._extract_date(text, r'to[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})') or
                    self._extract_date(text, r'(?:to|TO|To|-)[\s:]+(\d{1,2}[/-\.]\d{1,2}[/-\.]\d{2,4})')
                ),
                'opening_balance': (
                    self._extract_currency(text, r'Opening Balance[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'Balance Brought Forward[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:OPENING BALANCE|Opening Balance|Balance B/F)[\s:]+\$?([\d,]+\.?\d*)')
                ),
                'total_credits': (
                    self._extract_currency(text, r'Total Credits[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'Credits[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:TOTAL CREDITS|Total Credits|Total Deposits)[\s:]+\$?([\d,]+\.?\d*)')
                ),
                'total_debits': (
                    self._extract_currency(text, r'Total Debits[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'Debits[:\s]+\$?([\d,]+\.?\d*)') or
                    self._extract_currency(text, r'(?:TOTAL DEBITS|Total Debits|Total Withdrawals)[\s:]+\$?([\d,]+\.?\d*)')
                ),
                'raw_text': text[:500]
            }
            
            # Extract transactions if possible
            data['transactions_table'] = self._find_transactions(text)
            
            return data
        except Exception as e:
            logger.error(f"Error parsing bank statement from text: {e}")
            return {
                'document_type': 'bank_statement',
                'confidence': 0.1,
                'error': str(e),
                'extraction_status': 'failed',
                'raw_text': text[:100] if text else ""
            }
    
    def _parse_payslip_fields(self, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        fields = extracted_data.get('fields', {})
        
        # Parse table items into structured arrays
        earning_items = self._parse_table_items(fields, 'earning_item', {
            'type': ['earning_type', 'earning_item'],
            'hours': ['earning_hours'],
            'rate': ['earning_rate'],
            'this_period': ['earning_this_period'],
            'ytd': ['earning_ytd']
        })
        
        deduction_items = self._parse_table_items(fields, 'deduction_item', {
            'type': ['deduction_type', 'deduction_item'],
            'this_period': ['deduction_this_period'],
            'ytd': ['deduction_ytd']
        })
        
        superannuation_items = self._parse_table_items(fields, 'superannuation_item', {
            'type': ['superannuation_type', 'superannuation_item'],
            'this_period': ['superannuation_this_period'],
            'ytd': ['superannuation_ytd']
        })
        
        tax_items = self._parse_table_items(fields, 'tax_item', {
            'type': ['tax_type', 'tax_item'],
            'this_period': ['tax_this_period'],
            'ytd': ['tax_ytd']
        })
        
        # Using field names from Payslip_OCR_Labels.csv
        parsed_data = {
            'document_type': 'payslip',
            'confidence': extracted_data.get('confidence', 0.0),
            'employee_name': self._get_field_value(fields, ['employee_name']),
            'employer_name': self._get_field_value(fields, ['employer_name']),
            'abn': self._get_field_value(fields, ['abn']),
            'annual_salary': self._get_field_value(fields, ['annual_salary']),
            'base_income': self._get_field_value(fields, ['base_income']),
            'employee_classification': self._get_field_value(fields, ['employee_classification']),
            'employment_type': self._get_field_value(fields, ['employment_type']),
            'start_date': self._get_field_value(fields, ['start_date']),
            'end_date': self._get_field_value(fields, ['end_date']),
            'pay_date': self._get_field_value(fields, ['pay_date']),
            'gross_earnings': self._get_field_value(fields, ['gross_earnings']),
            'gross_earnings_ytd': self._get_field_value(fields, ['gross_earnings_ytd']),
            'net_pay': self._get_field_value(fields, ['net_pay']),
            'net_pay_ytd': self._get_field_value(fields, ['net_pay_ytd']),
            'page_number': self._get_field_value(fields, ['page_number']),
            # Structured table items arrays
            'earning_items': earning_items,
            'deduction_items': deduction_items,
            'superannuation_items': superannuation_items,
            'tax_items': tax_items,
            # Keep raw fields for debugging
            'raw_fields': fields
        }
        
        return parsed_data
    
    def _parse_table_items(self, fields: Dict[str, Any], item_key: str, field_mapping: Dict[str, list]) -> List[Dict[str, Any]]:
        """
        Parse table items from Document AI fields into structured arrays.
        
        Args:
            fields: Dictionary of extracted fields from Document AI
            item_key: The main item key (e.g., 'earning_item', 'deduction_item')
            field_mapping: Mapping of output keys to possible field names
                e.g., {'type': ['earning_type', 'earning_item'], 'amount': ['earning_this_period']}
        
        Returns:
            List of structured item dictionaries
        """
        items = []
        
        # Check if we have an array of items from grouped extraction
        if item_key in fields:
            field_data = fields[item_key]
            
            # If it's already a list (from grouped extraction)
            if isinstance(field_data, list):
                for item in field_data:
                    parsed_item = {}
                    # Extract value as type/description
                    if isinstance(item, dict):
                        if 'value' in item:
                            parsed_item['type'] = item['value']
                            parsed_item['description'] = item['value']
                        # Extract subfields from item properties
                        for output_key, possible_fields in field_mapping.items():
                            for field_name in possible_fields:
                                if field_name in item:
                                    value = item[field_name]
                                    if isinstance(value, dict):
                                        value = value.get('value', value)
                                    parsed_item[output_key] = value
                                    break
                    items.append(parsed_item)
            # If it's a single value, create one item
            elif field_data:
                item = {}
                if isinstance(field_data, dict):
                    if 'value' in field_data:
                        item['type'] = field_data['value']
                        item['description'] = field_data['value']
                else:
                    item['type'] = str(field_data)
                    item['description'] = str(field_data)
                items.append(item)
        
        # Also check for standalone subfields that might not be grouped
        # This handles cases where Document AI returns subfields separately
        standalone_items = {}
        for output_key, possible_fields in field_mapping.items():
            for field_name in possible_fields:
                if field_name in fields and field_name != item_key:
                    value = self._get_field_value(fields, [field_name])
                    if value:
                        # Try to match with existing items or create new ones
                        # For now, create a single item with all standalone fields
                        if 'items' not in standalone_items:
                            standalone_items['items'] = [{}]
                        standalone_items['items'][0][output_key] = value
        
        # Merge standalone items if we found any
        if 'items' in standalone_items:
            for standalone_item in standalone_items['items']:
                # Try to merge with existing items or add as new
                merged = False
                for existing_item in items:
                    # If type matches, merge
                    if existing_item.get('type') == standalone_item.get('type'):
                        existing_item.update(standalone_item)
                        merged = True
                        break
                if not merged and standalone_item:
                    items.append(standalone_item)
        
        return items
    
    def _parse_bank_statement_fields(self, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        fields = extracted_data.get('fields', {})
        
        # Using field names from Bank_statement_OCR_Labels.csv
        return {
            'document_type': 'bank_statement',
            'confidence': extracted_data.get('confidence', 0.0),
            'account_holder': self._get_field_value(fields, ['account_holder']),
            'account_number': self._get_field_value(fields, ['account_number']),
            'account_type': self._get_field_value(fields, ['account_type']),
            'bank_name': self._get_field_value(fields, ['bank_name']),
            'bsb': self._get_field_value(fields, ['bsb']),
            'client_name': self._get_field_value(fields, ['client_name']),
            'opening_balance': self._get_field_value(fields, ['opening_balance']),
            'page_count': self._get_field_value(fields, ['page_count']),
            'statement_date_range': self._get_field_value(fields, ['statement_date_range']),
            'statement_period_start': self._get_field_value(fields, ['statement_period_start']),
            'statement_period_end': self._get_field_value(fields, ['statement_period_end']),
            'total_credits': self._get_field_value(fields, ['total_credits']),
            'total_debits': self._get_field_value(fields, ['total_debits']),
            # Transactions table items
            'transactions_table': self._get_field_value(fields, ['transactions_table']),
            'credit_amount': self._get_field_value(fields, ['credit_amount']),
            'debit_amount': self._get_field_value(fields, ['debit_amount']),
            'description': self._get_field_value(fields, ['description']),
            'effective_date': self._get_field_value(fields, ['effective_date']),
            'posted_date': self._get_field_value(fields, ['posted_date']),
            'running_balance': self._get_field_value(fields, ['running_balance']),
            'raw_fields': fields
        }
    
    def _get_field_value(self, fields: Dict[str, Any], possible_keys: list) -> Optional[str]:
        try:
            for key in possible_keys:
                if key in fields:
                    field_data = fields[key]
                    if isinstance(field_data, dict):
                        return field_data.get('value')
                    # Handle currency values that might have symbols
                    if isinstance(field_data, str) and any(c in field_data for c in ['$', '£', '€']):
                        try:
                            # Clean currency value but return as string
                            return re.sub(r'[^\d.,]', '', field_data)
                        except Exception as e:
                            logger.warning(f"Error cleaning currency value: {e}")
                    return str(field_data) if field_data is not None else None
            return None
        except Exception as e:
            logger.warning(f"Error getting field value: {e}")
            return None
    
    def _extract_pattern(self, text: str, pattern: str, default: Optional[str] = None) -> Optional[str]:
        try:
            match = re.search(pattern, text, re.IGNORECASE)
            return match.group(1).strip() if match else default
        except Exception as e:
            logger.error(f"Error extracting pattern '{pattern}': {e}")
            return default
    
    def _extract_currency(self, text: str, pattern: str) -> Optional[float]:
        try:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value_str = match.group(1).strip()
                    # Remove currency symbols, commas, and other non-numeric characters except decimal point
                    value_str = re.sub(r'[^\d.]', '', value_str.replace(',', ''))
                    return float(value_str) if value_str else None
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to convert currency value: {match.group(1)} - Error: {e}")
                    return None
            return None
        except Exception as e:
            logger.error(f"Error extracting currency with pattern '{pattern}': {e}")
            return None
    
    def _extract_date(self, text: str, pattern: str) -> Optional[str]:
        try:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip()
                try:
                    for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y']:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            return dt.strftime('%Y-%m-%d')
                        except ValueError:
                            continue
                except Exception:
                    pass
                return date_str
            return None
        except Exception as e:
            logger.error(f"Error extracting date with pattern '{pattern}': {e}")
            return None
    
    def _extract_earning_items(self, text: str) -> list:
        """Extract earning items like commission, overtime, allowances, bonuses from payslip text"""
        earning_items = []
        
        try:
            # Keywords to look for in earning items
            earning_keywords = [
                ('commission', r'(commission|comm\.?)'),
                ('bonus', r'(bonus|incentive|performance\s+pay)'),
                ('overtime', r'(overtime|ot|o/t|extra\s+hours)'),
                ('shift', r'(shift\s+loading|shift\s+allowance|penalty\s+rate)'),
                ('allowance', r'(phone\s+allowance|travel\s+allowance|meal\s+allowance|tool\s+allowance|allowance|allow\.?)'),
                ('base', r'(base\s+hourly|ordinary\s+hours|ordinary\s+pay|regular\s+hours)'),
                ('leave', r'(annual\s+leave\s+pay|sick\s+leave|leave\s+pay)'),
            ]
            
            lines = text.split('\n')
            for line in lines:
                for keyword, pattern in earning_keywords:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        try:
                            # Extract the full description
                            description = line.strip()
                            
                            # Try to find all amounts in the line
                            amount_matches = re.findall(r'\$?([\d,]+\.\d{2})', line)
                            if not amount_matches:
                                continue
                            
                            # Smart amount selection based on line structure
                            # Common patterns:
                            # 1. "Description Hours Rate Amount YTD Type" - want Amount (2nd to last)
                            # 2. "Description Amount YTD" - want Amount (first)
                            # 3. "Commission $0.00 $61,257.90 Wages" - want both (this_period=0, ytd=61257.90)
                            
                            # Try to extract hours first
                            hours_match = re.search(r'^\s*[A-Za-z\s]+\s+(\d+\.?\d*)\s+\$', line)
                            hours = float(hours_match.group(1)) if hours_match else None
                            
                            # Try to extract rate
                            rate_match = re.search(r'\$(\d+\.\d{2})\s+\$', line)
                            rate = float(rate_match.group(1)) if rate_match else None
                            
                            # Determine which amount is "this period" and which is YTD
                            if len(amount_matches) >= 3:
                                # Pattern: Hours Rate Amount YTD - take 2nd to last
                                amount = float(amount_matches[-2].replace(',', ''))
                                ytd = float(amount_matches[-1].replace(',', ''))
                            elif len(amount_matches) == 2:
                                # Pattern: Amount YTD - first is this period
                                amount = float(amount_matches[0].replace(',', ''))
                                ytd = float(amount_matches[1].replace(',', ''))
                            else:
                                # Only one amount
                                amount = float(amount_matches[0].replace(',', ''))
                                ytd = None
                            
                            # Keep items even if this_period is 0 but YTD has value (important for commission/bonus)
                            # Only skip if both are 0
                            if amount == 0 and (ytd is None or ytd == 0):
                                continue
                            
                            earning_items.append({
                                'type': keyword.title(),
                                'description': description,
                                'this_period': amount,
                                'ytd': ytd,
                                'hours': hours,
                                'rate': rate
                            })
                        except Exception as e:
                            logger.debug(f"Error parsing earning item from line '{line[:50]}': {e}")
                            continue
            
            # Remove duplicates based on type and amount
            seen = set()
            unique_items = []
            for item in earning_items:
                key = (item['type'], item['this_period'])
                if key not in seen:
                    seen.add(key)
                    unique_items.append(item)
            
            return unique_items
            
        except Exception as e:
            logger.error(f"Error extracting earning items: {e}")
            return []
    
    def _extract_deduction_items(self, text: str) -> list:
        """Extract deduction items like tax, super, salary sacrifice from payslip text"""
        deduction_items = []
        
        try:
            # Keywords to look for in deduction items
            deduction_keywords = [
                ('tax', r'(tax|payg|withholding|income\s+tax)\s+.*?\$?([\d,]+\.?\d*)'),
                ('superannuation', r'(super|superannuation|sg|retirement)\s+.*?\$?([\d,]+\.?\d*)'),
                ('salary_sacrifice', r'(salary\s+sacrifice|sal\s+sac|packaging)\s+.*?\$?([\d,]+\.?\d*)'),
            ]
            
            lines = text.split('\n')
            for line in lines:
                for keyword, pattern in deduction_keywords:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        try:
                            # Extract the full description and amount
                            description = line.strip()[:100]
                            
                            # Try to find amount in the line (look for negative or in parentheses)
                            amount_match = re.findall(r'[\(\-]?\$?([\d,]+\.\d{2})[\)]?', line)
                            if amount_match:
                                # Take the last amount found
                                amount_str = amount_match[-1].replace(',', '')
                                amount = float(amount_str)
                                
                                deduction_items.append({
                                    'type': keyword.replace('_', ' ').title(),
                                    'description': description,
                                    'this_period': amount
                                })
                        except Exception as e:
                            logger.debug(f"Error parsing deduction item: {e}")
                            continue
            
            # Remove duplicates
            seen = set()
            unique_items = []
            for item in deduction_items:
                key = (item['type'], item['this_period'])
                if key not in seen:
                    seen.add(key)
                    unique_items.append(item)
            
            return unique_items
            
        except Exception as e:
            logger.error(f"Error extracting deduction items: {e}")
            return []
    
    def _find_transactions(self, text: str) -> dict:
        """Extract transaction information from bank statement text."""
        try:
            transactions = []
            lines = text.split('\n')
            
            # Look for transaction table patterns
            transaction_patterns = [
                r'(\d{1,2}[/-\.]\d{1,2}[/-\.]\d{2,4}).*?(\$?[\d,]+\.?\d*).*?(credit|debit|deposit|withdrawal|payment)',
                r'(\d{1,2}[/-\.]\d{1,2}[/-\.]\d{2,4}).*?([\w\s]+).*?(\$?[\d,]+\.?\d*)'
            ]
            
            for line in lines:
                for pattern in transaction_patterns:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        try:
                            date_str = match.group(1)
                            description = line.strip()[:100]
                            amount_str = re.search(r'\$?([\d,]+\.?\d*)', line)
                            amount = float(amount_str.group(1).replace(',', '')) if amount_str else 0.0
                            
                            transactions.append({
                                'date': date_str,
                                'description': description,
                                'amount': amount
                            })
                        except Exception as e:
                            logger.warning(f"Error parsing transaction: {e}")
                        break
            
            # Determine if statement contains transactions
            contains_transactions = len(transactions) > 0
            
            # Find salary deposits
            salary_deposits = self._find_salary_deposits(text, transactions)
            
            return {
                'transactions': transactions[:10],  # Limit to 10 transactions
                'contains_transactions': contains_transactions,
                'salary_deposits': salary_deposits
            }
        except Exception as e:
            logger.error(f"Error finding transactions: {e}")
            return {
                'transactions': [],
                'salary_deposits': [],
                'contains_transactions': False,
                'error': str(e)
            }
    
    def _find_salary_deposits(self, text: str, transactions=None) -> list:
        """Extract salary deposits from bank statement text or transactions."""
        try:
            deposits = []
            
            if transactions is None:
                transactions = []
                lines = text.split('\n')
                
                # Multiple patterns to identify salary deposits
                salary_patterns = [
                    r'(salary|pay|wage|income)',
                    r'(direct credit|deposit|transfer)',
                    r'(payroll|remuneration)'
                ]
                
                for line in lines:
                    for pattern in salary_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            amount = self._extract_currency(line, r'\$?([\d,]+\.?\d*)')
                            date_match = re.search(r'(\d{1,2}[/-\.]\d{1,2}[/-\.]\d{2,4})', line)
                            date_str = date_match.group(1) if date_match else 'Unknown'
                            
                            if amount and amount > 500:  # Lower threshold to catch more potential salary payments
                                description = line.strip()[:100]
                                deposits.append({
                                    'date': date_str,
                                    'amount': amount,
                                    'description': description
                                })
                            break  # Once we find a match in a line, no need to check other patterns
            else:
                # Use provided transactions to find salary deposits
                salary_patterns = [
                    r'(salary|pay|wage|income)',
                    r'(direct credit|deposit|transfer)',
                    r'(payroll|remuneration)'
                ]
                
                for transaction in transactions:
                    description = transaction.get('description', '')
                    for pattern in salary_patterns:
                        if re.search(pattern, description, re.IGNORECASE):
                            amount = transaction.get('amount', 0)
                            if amount and amount > 500:
                                deposits.append(transaction)
                            break
            
            # Remove duplicates based on amount
            unique_deposits = []
            seen_amounts = set()
            
            for deposit in deposits:
                if deposit['amount'] not in seen_amounts:
                    seen_amounts.add(deposit['amount'])
                    unique_deposits.append(deposit)
                    
            return unique_deposits[:5]  # Return top 5 potential salary deposits
        except Exception as e:
            logger.error(f"Error finding salary deposits: {e}")
            return []
