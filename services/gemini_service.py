import os
import json
import logging
from typing import Dict, Any, List
import vertexai
from vertexai.generative_models import GenerativeModel, Part

logger = logging.getLogger(__name__)

class GeminiService:
    def __init__(self):
        try:
            # Initialize Vertex AI - NO FALLBACK ALLOWED
            project_id = os.environ.get('GCP_PROJECT_ID', 'genai-hackathon-25')
            location = os.environ.get('GCP_LOCATION', 'us-central1')
            
            if not project_id:
                raise ValueError("GCP_PROJECT_ID environment variable is not set!")
            
            logger.info(f"Initializing Vertex AI with project: {project_id}, location: {location}")
            
            vertexai.init(project=project_id, location=location)
            self.model = GenerativeModel("gemini-2.5-flash")
            self.client_available = True
            
            logger.info(f"✅ Vertex AI Gemini service initialized successfully!")
            logger.info(f"   Project: {project_id}")
            logger.info(f"   Location: {location}")
            logger.info(f"   Model: gemini-2.5-flash")
            
        except Exception as e:
            logger.error(f"❌ CRITICAL: Vertex AI initialization failed: {e}")
            logger.error("   Standard Income policy checks will NOT work without Vertex AI!")
            self.model = None
            self.client_available = False
            raise RuntimeError(f"Vertex AI is required but failed to initialize: {e}")
    
    
    def classify_document(self, filepath: str, text_content: str = "") -> str:
        """
        Classify document type using content-based heuristics and AI, falling back to filename.
        """
        filename = os.path.basename(filepath).lower()
            
        # 1. Content-based heuristics (Fastest and most reliable if text exists)
        if text_content and len(text_content.strip()) > 50:
            text_lower = text_content.lower()
            
            # Strong Payslip indicators
            payslip_indicators = ['payslip', 'pay slip', 'net pay', 'ytd gross', 'tax withheld', 'superannuation', 'pay period', 'employer:', 'employee:']
            payslip_score = sum(1 for keyword in payslip_indicators if keyword in text_lower)
            
            # Strong Bank Statement indicators
            bank_indicators = ['statement of account', 'opening balance', 'closing balance', 'bsb', 'account number', 'total credits', 'total debits', 'deposits', 'withdrawals']
            bank_score = sum(1 for keyword in bank_indicators if keyword in text_lower)
            
            # High threshold for definitive heuristic match
            if payslip_score >= 2 and payslip_score > bank_score:
                logger.info(f"Classified {filename} as payslip based on content heuristics (score: {payslip_score})")
                return 'payslip'
            elif bank_score >= 2 and bank_score > payslip_score:
                logger.info(f"Classified {filename} as bank_statement based on content heuristics (score: {bank_score})")
                return 'bank_statement'
                
        # 2. AI Classification for ambiguous text or images without text
        if self.client_available and self.model:
            try:
                logger.info(f"Using Vertex AI to classify ambiguous document {filename}")
                
                if text_content and len(text_content.strip()) > 50:
                    prompt = f"""Analyze the provided document text and classify it into exactly one of these categories: 'payslip' or 'bank_statement'.
If the text does not clearly belong to either category, return 'unknown'.
Return ONLY the category name in lowercase block. No other text or explanation.

Document Text (first 2500 chars):
{text_content[:2500]}
"""
                    contents = [prompt]
                else:
                    logger.info(f"No text extracted for {filename}, sending file binary to Gemini multimodal")
                    prompt = """Analyze this document visually and classify it into exactly one of these categories: 'payslip' or 'bank_statement'.
If the document does not clearly belong to either category, return 'unknown'.
Return ONLY the category name in lowercase block. No other text or explanation."""
                    
                    with open(filepath, "rb") as f:
                        file_data = f.read()
                        
                    mime_type = "application/pdf"
                    if filepath.lower().endswith(('.png', '.jpg', '.jpeg')):
                        mime_type = "image/jpeg"
                        
                    document_part = Part.from_data(data=file_data, mime_type=mime_type)
                    contents = [document_part, prompt]

                response = self.model.generate_content(contents)
                classification = response.text.strip().lower()
                
                # Clean up response (sometimes Gemini returns "payslip\n" or "```payslip```")
                classification = classification.replace('```', '').strip()
                
                if classification in ['payslip', 'bank_statement', 'unknown']:
                    logger.info(f"Vertex AI classified {filename} as: {classification}")
                    return classification
            except Exception as e:
                logger.warning(f"AI classification failed, falling back to heuristics: {e}")

        # 3. Filename-based heuristics (Terminal fallback)
        logger.info(f"Using filename fallback classification for {filename}")
        bank_keywords = ['bank', 'statement', 'account', 'transaction', 'balance', 'commonwealth', 'westpac', 'anz', 'nab', 'cba']
        payslip_keywords = ['payslip', 'pay', 'salary', 'wage', 'payroll', 'employee', 'paystub']
        
        bank_score_fn = sum(1 for keyword in bank_keywords if keyword in filename)
        payslip_score_fn = sum(1 for keyword in payslip_keywords if keyword in filename)
        
        if bank_score_fn > payslip_score_fn:
            logger.info(f"Classified {filename} as bank_statement (filename score: {bank_score_fn})")
            return 'bank_statement'
        elif payslip_score_fn > bank_score_fn:
            logger.info(f"Classified {filename} as payslip (filename score: {payslip_score_fn})")
            return 'payslip'
        else:
            if any(keyword in filename for keyword in ['statement', 'bank', 'account']):
                return 'bank_statement'
            elif any(keyword in filename for keyword in ['pay', 'salary', 'payslip']):
                return 'payslip'
            
            logger.warning(f"Could not classify {filename}, returning unknown")
            return 'unknown'
    
    def generate_application_summary(self, processed_docs: List[Dict[str, Any]], 
                                    validation_results: Dict[str, Any]) -> str:
        if not self.client_available:
            return self._generate_fallback_summary(processed_docs, validation_results)
        
        try:
            summary_data = {
                'documents': [],
                'validation_summary': validation_results.get('summary', {})
            }
            
            for doc in processed_docs:
                summary_data['documents'].append({
                    'type': doc.get('document_type'),
                    'filename': doc.get('filename'),
                    'key_data': doc.get('extracted_data', {})
                })
            
            prompt = f"""You are a mortgage assessor AI assistant. Generate a comprehensive, professional summary of this mortgage application.

Application Data:
{json.dumps(summary_data, indent=2)}

Generate a summary that includes:
1. Applicant Overview: Key details about the applicant from documents
2. Income Assessment: Analysis of income sources, stability, and amounts
3. Document Quality: Completeness and quality of submitted documents
4. Validation Status: Overview of passed and failed checks
5. Risk Factors: Any concerns or items requiring attention
6. Recommendation: Brief assessment conclusion

Keep the summary professional, clear, and concise (250-400 words)."""

            response = self.model.generate_content(prompt)
            
            return response.text or self._generate_fallback_summary(processed_docs, validation_results)
        
        except Exception as e:
            logger.error(f"Error generating summary with Vertex AI: {e}")
            return self._generate_fallback_summary(processed_docs, validation_results)
    
    def analyze_all_policies_batched(self, policy_checks: List[tuple], document_data: Dict[str, Any], all_policies: Dict[str, str]) -> str:
        """
        Analyze ALL 18 Standard Income policies in a single batched AI call.
        This is much more efficient and avoids quota limits.
        
        Args:
            policy_checks: List of (policy_key, policy_name) tuples
            document_data: Complete extracted data including payslip, bank statements, etc.
            all_policies: Dictionary containing all policy details
            
        Returns:
            A comprehensive string with analysis for all 12 policies
        """
        if not self.client_available:
            logger.error("Vertex AI is not available for batched policy analysis!")
            return "ERROR: Vertex AI (Gemini) is not configured. Cannot analyze policies. Please check GCP_PROJECT_ID and credentials."
        
        try:
            # Load policy config for keyword matching
            import json
            import os
            config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'standard_income_policy_config.json')
            policy_config = {}
            try:
                with open(config_file, 'r') as f:
                    policy_config = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load policy config: {e}")
            
            # Extract key information from document data
            payslip_data = document_data.get('payslip', {})
            all_payslips = document_data.get('all_payslips', [])
            bank_statements = document_data.get('bank_statements', [])
            
            # Build comprehensive context with ALL extracted data
            context_summary = f"""
PAYSLIP DATA SUMMARY:
- Employee Name: {payslip_data.get('employee_name', 'Not found')}
- Employer Name: {payslip_data.get('employer_name', 'Not found')}
- Employment Type: {payslip_data.get('employment_type', 'Not specified')}
- Employee Classification: {payslip_data.get('employee_classification', 'Not specified')}
- Pay Date: {payslip_data.get('pay_date', 'Not found')}
- Pay Period: {payslip_data.get('start_date', 'N/A')} to {payslip_data.get('end_date', 'N/A')}
- Gross Earnings: {payslip_data.get('gross_earnings', payslip_data.get('gross_pay', 'Not found'))}
- Net Pay: {payslip_data.get('net_pay', 'Not found')}
- Base Income: {payslip_data.get('base_income', 'Not found')}
- Annual Salary: {payslip_data.get('annual_salary', 'Not found')}
- YTD Gross: {payslip_data.get('gross_earnings_ytd', 'Not found')}
- YTD Net: {payslip_data.get('net_pay_ytd', 'Not found')}
- Superannuation: {payslip_data.get('superannuation', payslip_data.get('superannuation_this_period', 'Not found'))}
- Tax Withheld: {payslip_data.get('tax_withheld', payslip_data.get('tax_this_period', 'Not found'))}

COMPLETE EARNINGS BREAKDOWN (ALL ITEMS):
{self._format_earnings_items(payslip_data)}

COMPLETE DEDUCTIONS BREAKDOWN (ALL ITEMS):
{self._format_deduction_items(payslip_data)}

SUPERANNUATION ITEMS (ALL OCCURRENCES):
{self._format_superannuation_items(payslip_data)}

TAX ITEMS (ALL OCCURRENCES):
{self._format_tax_items(payslip_data)}

ADDITIONAL CONTEXT:
- Total Payslips Provided: {document_data.get('payslip_count', 0)}
- Bank Statements Provided: {document_data.get('bank_statement_count', 0)}
- All Payslips Data Available: {len(document_data.get('all_payslips', []))} payslip(s)
"""
            
            # Build the list of all 12 policies with their requirements
            policies_list = ""
            for idx, (policy_key, policy_name) in enumerate(policy_checks, 1):
                policy_details = all_policies.get(policy_key, "No details available")
                policies_list += f"\n## {idx}. {policy_name}\n"
                policies_list += f"Requirements: {policy_details}\n"
                
                # Add keyword matching hints from policy config
                if policy_config and 'policy_matching_rules' in policy_config:
                    for config_policy_name, config_data in policy_config['policy_matching_rules'].items():
                        if config_policy_name.lower() in policy_name.lower():
                            policies_list += f"Keywords to search: {', '.join(config_data.get('pass_if_found', [])[:10])}\n"
                            policies_list += f"Field locations: {', '.join(config_data.get('field_locations', []))}\n"
                            break
            
            prompt = f"""You are an expert data extraction specialist for mortgage applications. Your ONLY task is to extract and summarize relevant information from payslips.

CRITICAL: You MUST extract and show ALL occurrences of items. For example:
- If there are 3 superannuation items, show ALL 3 with their types and amounts
- If there are 5 earning items (base salary, overtime, allowances, bonus, commission), show ALL 5
- If there are multiple allowances, show EACH one separately with its type and amount
- Look for base income in ALL possible places: earning_items with types like "Ordinary Hours", "Normal Hours", "Base Hourly", "Monthly Base Salary", "Fortnightly Salary", etc.

APPLICANT'S DOCUMENT DATA:
{context_summary}

COMPLETE PAYSLIP DATA (for detailed analysis - includes ALL extracted fields):
{json.dumps(payslip_data, indent=2, default=str)}

POLICY CONFIGURATION (use these keywords to find relevant data):
{json.dumps(policy_config.get('policy_matching_rules', {}), indent=2)}

THE 18 STANDARD INCOME POLICIES TO ANALYZE:
{policies_list}

YOUR TASK:
For EACH policy, extract and summarize ONLY the relevant data found in the payslip. Look through ALL fields including earning_items, deduction_items, tax_items, and all other fields to find relevant data even if it's categorized differently than expected.

SPECIAL CLASSIFICATION RULE:
- If "Social Club Fund" or similar (social club, club fund) is found in deduction_items, classify it as Allowances (80%) policy, NOT as a deduction.

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:

## 1. Standard Income (tenure)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [1-2 sentences with key quantifiable info only, e.g., "Full-time employment, 3 months tenure"]
**Additional Details**: [Show ALL relevant data found: employment_type value, employee_classification value, any tenure indicators, YTD figures that indicate duration, pay period dates]

## 2. Base income (100%)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY show monthly/this pay amount, e.g., "$4,500 per period" - DO NOT include annual salary or servicing in summary]
**Additional Details**: [CRITICAL: Show ALL items that could be base income. List EVERY earning_item with its type (e.g., "Ordinary Hours", "Normal Hours", "Base Hourly", "Monthly Base Salary", "Fortnightly Salary", "Ordinary Pay", "Ordinary Time", "Salary", "Normal Pay", etc.) and this_period amount. Also show base_income field value, annual_salary value, gross_earnings value. IMPORTANT: Base income can be labeled in many ways - extract ALL occurrences from earning_items array, not just the "base_income" field. Show each item separately with its type and this_period amount. In summary, ONLY show the monthly/this pay amount extracted from earning_items, NOT the annual salary.]

## 3. Casual income (100%)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted amount, e.g., "$2,000 casual income" OR "No casual income found"]
**Additional Details**: [Show ALL casual-related data: any earning_items with "casual" in type, casual_hours field, hourly_rate field, casual loading items - list everything with amounts. Show calculation: Total amount × 100% = Servicing amount]

## 4. Second Job (100%)
**Status**: [NOT_APPLICABLE]
**Summary**: [e.g., "No second job identified"]
**Additional Details**: [Show employer_name field, any indicators of multiple employers]

## 5. Overtime / shift allowance (80%)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$1,000 overtime/shift allowance"]
**Additional Details**: [CRITICAL: Show ALL items that could be overtime/shift. List EVERY earning_item that contains words like overtime, OT, o/t, shift, shift loading, shift allowance, penalty, penalty rate, extra hours, additional hours, weekend, night, Saturday shift, Sunday shift, night shift - show type, this_period amount, and YTD for each. Also check for overtime field. IMPORTANT: Look for variations like "Overtime @ 1.5", "Overtime @ DT", "Shift Loading", "Saturday Shift", etc. Show calculation: Sum of all items = Total, Total × 80% = Servicing amount]

## 6. Bonus/Commission (80%)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$3,500 bonus/commission"]
**Additional Details**: [CRITICAL: Show ALL items that could be bonus/commission. List EVERY earning_item with words like bonus, commission, incentive, performance pay, performance bonus, annual bonus, quarterly bonus, monthly bonus, sales commission, sales bonus, productivity bonus, retention bonus, signing bonus - show type, this_period amount, and YTD for each. IMPORTANT: Extract ALL occurrences, even if labeled differently. Show calculation: Sum of all items = Total, Total × 80% = Servicing amount]

## 7. Fully Maintained Car Benefits (100%)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$10,400/year car benefits" OR "No car benefits found"]
**Additional Details**: [Show ALL items with car/vehicle/motor: list any earning_items with these words, show amounts and annualization calculation. Show calculation: Total amount × 100% = Servicing amount]

## 8. Allowances (80%)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$300 allowances"]
**Additional Details**: [CRITICAL: Show ALL allowance items. List EVERY earning_item OR deduction_item with "allowance" in type or description (travel allowance, meal allowance, uniform allowance, tool allowance, phone allowance, mobile allowance, expense allowance, laundry allowance, accommodation allowance, site allowance, first aid allowance, location allowance, etc.). IMPORTANT: If "Social Club Fund" or similar is found in deduction_items, include it here as an allowance. Show type, this_period amount, and YTD for each. Extract ALL occurrences separately. Show calculation: Sum of all items = Total, Total × 80% = Servicing amount]

## 9. Superannuation Contributions (Employer) (100%)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$650 employer super contributions"]
**Additional Details**: [Show ONLY superannuation items that do NOT contain sacrifice/packaging keywords. List each item with type, fund name, and this_period amount. Include superannuation field values. Show calculation: Sum of all qualifying items = Total, Total × 100% = Servicing amount.]

## 10. Salary Sacrifice and Salary Packaging Arrangements (100%)
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$220 salary sacrifice"]
**Additional Details**: [Show ONLY items whose type/description contains sacrifice keywords (salary sacrifice, sal sac, packaging, novated lease, fringe benefit, sacrifice). List every item with type and this_period amount, including deduction_items and superannuation_items. Show calculation: Sum of all sacrifice items = Total, Total × 100% = Servicing amount.]

## 11. Parental Leave (Employer or Government)
**Status**: [NOT_APPLICABLE]
**Summary**: [ONLY amounts if found, e.g., "$0" OR "No parental leave identified"]
**Additional Details**: [Show any earning_items with parental/maternity/paternity in type, if any found show amounts]

## 12. Standard Income Verification
**Status**: [PASS/FAIL/WARNING]
**Summary**: [e.g., "2 payslips provided, meets requirement" OR "1 payslip with YTD figures"]
**Additional Details**: [Show: number of payslips provided, YTD fields present (gross_earnings_ytd, net_pay_ytd values), whether YTD data is available]

## 13. Document requirements
**Status**: [PASS/FAIL/WARNING]
**Summary**: [e.g., "All required fields present, document is 15 days old"]
**Additional Details**: [Show: employee_name value, employer_name value, abn value, pay_date value, calculate days old from pay_date to today, list any missing required fields]

## 14. Pre-Tax Deduction
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$500 pre-tax deductions" OR "No pre-tax deductions found"]
**Additional Details**: [CRITICAL: Show ALL pre-tax deduction items. List EVERY deduction_item with pre-tax indicators (pre tax, pre-tax, before tax, salary sacrifice, salary packaging, novated lease, fringe benefit, social club fund, union fees, health insurance, private health, etc.) - show type, this_period amount, and YTD for each. IMPORTANT: Extract ALL occurrences separately. Note: Social Club Fund should also be classified under Allowances policy, but show it here too for completeness.]

## 15. Post-Tax Deduction
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$120 post-tax deductions" OR "No post-tax deductions found"]
**Additional Details**: [Show ALL deduction_items that indicate post-tax/after-tax deductions (keywords: post tax, after tax, net deduction, union fees, private health, social club, charity, loan repayment). List each with this_period amount and YTD if available. Sum them and show calculation.]

## 16. Tax
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total tax amount, e.g., "$1,200 tax" OR "No tax information found"]
**Additional Details**: [CRITICAL: Show ALL tax items EXCLUDING STSL/HELP-style items. List EVERY qualifying tax_item with its type (e.g., "PAYG Tax", "Income Tax", "Tax Withheld", "PAYG Withholding") and this_period amount. Also show tax_withheld field value, tax_this_period value. IMPORTANT: Exclude items containing STSL, HECS, HELP, VET FEE-HELP (these belong in Non-income items). Show calculation: Sum of remaining tax items = Total tax amount.]

## 17. Net Pay and Gross Pay
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted values, e.g., "Gross: $5,000, Net: $3,800"]
**Additional Details**: [Show: net_pay value, gross_pay value (or gross_earnings value), net_pay_ytd value, gross_earnings_ytd value. These are parent label fields that summarize the payslip totals.]

## 18. Non-income items
**Status**: [PASS/FAIL/WARNING/NOT_APPLICABLE]
**Summary**: [ONLY extracted total amount, e.g., "$150 STSL + $200 Annual Leave = $350"]
**Additional Details**: [CRITICAL: Collect ALL STSL/HELP/education loan repayments AND any annual leave/leave loading/holiday pay amounts (found in tax_items, deduction_items, or earning_items). List each item with its source and amount. These items must NOT appear in the Tax policy. Show sum of all non-income items and clearly label STSL vs annual leave values.]

CRITICAL RULES:
1. For QUANTIFIABLE POLICIES (Base income, Casual, Second Job, Overtime/shift, Bonus/Commission, Car Benefits, Allowances, Superannuation Contributions, Salary Sacrifice, Parental Leave, Pre-Tax Deduction, Post-Tax Deduction, Tax, Net/Gross Pay, Non-income items): Summary MUST show ONLY the extracted amount(s) (no servicing calculations). Format: concise amounts like "$X" or "Gross: $X, Net: $Y".
2. For Base Income specifically: Summary MUST show ONLY the monthly/this pay amount from earning_items, NOT annual salary and NOT servicing. Annual salary and servicing should be in Additional Details only.
3. For items with servicing (80% or 100%): perform and EXPLAIN the servicing calculation ONLY in Additional Details, not in Summary.
4. Additional Details MUST show ALL relevant data found - list every earning_item, deduction_item, tax_item, or field that could relate to the policy, even if the naming is different, and include the calculation: "Sum of all items = Total, Total × servicing% = Servicing amount" where applicable.
5. Use BROAD keyword matching - look for partial matches, synonyms, related terms (e.g., for bonus: bonus, incentive, performance pay, commission, etc.)
6. DO NOT say "searched for" or "looking for" - ONLY show what was actually FOUND in the data
7. If nothing found, say "No relevant items found in payslip data" and list the fields that were checked
8. Status should be: PASS (found with amount > 0), FAIL (should exist but not found), WARNING (found but unclear), NOT_APPLICABLE (doesn't apply)
9. Always show actual field names and values from the payslip data
10. IMPORTANT: If "Social Club Fund" or similar is found in deduction_items, classify it as Allowances (80%) policy, but also show it in both Pre-Tax or Post-Tax (depending on deduction label) for completeness. STSL/HELP items must ONLY appear under Non-income items, NOT under Tax.

Extract and summarize now:"""

            logger.info("Making single batched AI call for all 18 Standard Income policies...")
            response = self.model.generate_content(prompt)
            
            if response and response.text:
                logger.info("Successfully received batched analysis for all 18 policies")
                return response.text
            else:
                logger.error("Empty response from Vertex AI for batched policy analysis")
                return "ERROR: Vertex AI returned an empty response for batched policy analysis. Please check the model configuration."
            
        except Exception as e:
            logger.error(f"Error in batched policy analysis with Vertex AI: {e}", exc_info=True)
            return f"ERROR: Failed to analyze policies in batch with Vertex AI: {str(e)}. Please check Vertex AI configuration and credentials."
    
    def analyze_policy_check(self, policy_name: str, document_data: Dict[str, Any], policy_details: str, all_policies: Dict[str, str] = None) -> str:
        """
        Analyze a specific policy check against document data using Vertex AI (Gemini).
        This method provides comprehensive analysis with full payslip context.
        
        Args:
            policy_name: Name of the policy being checked
            document_data: Complete extracted data including payslip, bank statements, etc.
            policy_details: Details of the policy requirements from the policy sheet
            all_policies: Dictionary containing all policies for broader context
            
        Returns:
            A string with intelligent analysis of the policy check
        """
        if not self.client_available:
            logger.error("Vertex AI is not available for policy analysis!")
            return f"ERROR: Vertex AI (Gemini) is not configured. Cannot analyze {policy_name}. Please check GCP_PROJECT_ID and credentials."
        
        try:
            # Extract key information from document data
            payslip_data = document_data.get('payslip', {})
            all_payslips = document_data.get('all_payslips', [])
            bank_statements = document_data.get('bank_statements', [])
            
            # Build comprehensive context
            context_summary = f"""
PAYSLIP DATA SUMMARY:
- Employee Name: {payslip_data.get('employee_name', 'Not found')}
- Employer Name: {payslip_data.get('employer_name', 'Not found')}
- Employment Type: {payslip_data.get('employment_type', 'Not specified')}
- Employee Classification: {payslip_data.get('employee_classification', 'Not specified')}
- Pay Date: {payslip_data.get('pay_date', 'Not found')}
- Pay Period: {payslip_data.get('start_date', 'N/A')} to {payslip_data.get('end_date', 'N/A')}
- Gross Earnings: {payslip_data.get('gross_earnings', payslip_data.get('gross_pay', 'Not found'))}
- Net Pay: {payslip_data.get('net_pay', 'Not found')}
- Base Income: {payslip_data.get('base_income', 'Not found')}
- YTD Gross: {payslip_data.get('gross_earnings_ytd', 'Not found')}
- YTD Net: {payslip_data.get('net_pay_ytd', 'Not found')}
- Superannuation: {payslip_data.get('superannuation', payslip_data.get('superannuation_this_period', 'Not found'))}
- Tax Withheld: {payslip_data.get('tax_withheld', payslip_data.get('tax_this_period', 'Not found'))}

EARNINGS BREAKDOWN:
{self._format_earnings_items(payslip_data)}

DEDUCTIONS BREAKDOWN:
{self._format_deduction_items(payslip_data)}

ADDITIONAL CONTEXT:
- Total Payslips Provided: {document_data.get('payslip_count', 0)}
- Bank Statements Provided: {document_data.get('bank_statement_count', 0)}
"""
            
            # Include related policies for context
            related_policies = ""
            if all_policies:
                related_policies = "\n\nRELATED STANDARD INCOME POLICIES FOR CONTEXT:\n"
                for p_name, p_details in all_policies.items():
                    if p_name != policy_name and p_details:
                        related_policies += f"\n{p_name}:\n{p_details[:200]}...\n"
            
            prompt = f"""You are an expert mortgage policy analyst specializing in Standard (regular employment) income verification for residential mortgages.

POLICY TO ANALYZE: {policy_name}

POLICY REQUIREMENTS:
{policy_details}
{related_policies}

APPLICANT'S DOCUMENT DATA:
{context_summary}

COMPLETE PAYSLIP DATA (for detailed analysis):
{json.dumps(payslip_data, indent=2)}

YOUR TASK:
Analyze the provided payslip data against the "{policy_name}" policy requirements and provide a comprehensive summary that includes:

1. **Relevant Findings**: What specific information from the payslip is relevant to this policy?
2. **Policy Compliance**: Does the applicant meet, partially meet, or fail to meet this policy requirement?
3. **Extracted Values**: List any specific amounts, dates, or values found that relate to this policy
4. **Servicing Impact**: How does this affect the mortgage servicing calculation (e.g., 80%, 100%, or not included)?
5. **Additional Verification**: What additional documents or verification might be needed?
6. **Risk Assessment**: Any concerns or red flags related to this policy?

IMPORTANT GUIDELINES:
- Be specific and cite actual values from the payslip
- If information is missing, clearly state what's missing
- Consider YTD (Year-to-Date) figures when available
- Look for patterns across multiple payslips if provided
- Pay special attention to superannuation, deductions, and earning items
- Provide actionable insights for the mortgage assessor

Provide your analysis in 150-250 words, being thorough yet concise."""

            response = self.model.generate_content(prompt)
            
            if response and response.text:
                return response.text
            else:
                logger.error(f"Empty response from Vertex AI for policy: {policy_name}")
                return f"ERROR: Vertex AI returned an empty response for {policy_name}. Please check the model configuration."
            
        except Exception as e:
            logger.error(f"Error analyzing policy with Vertex AI: {e}", exc_info=True)
            return f"ERROR: Failed to analyze {policy_name} with Vertex AI: {str(e)}. Please check Vertex AI configuration and credentials."
    
    def _format_earnings_items(self, payslip_data: Dict[str, Any]) -> str:
        """Format earnings items for better readability - shows ALL items with complete details"""
        earnings = []
        
        # Check for earning_items array (structured from Document AI)
        if 'earning_items' in payslip_data and payslip_data['earning_items']:
            for idx, item in enumerate(payslip_data['earning_items'], 1):
                if isinstance(item, dict):
                    item_type = item.get('type', item.get('description', 'Unknown'))
                    this_period = item.get('this_period', item.get('earning_this_period', 0))
                    ytd = item.get('ytd', item.get('earning_ytd', None))
                    hours = item.get('hours', item.get('earning_hours', None))
                    rate = item.get('rate', item.get('earning_rate', None))
                    
                    # Format with all available details
                    details = []
                    if hours:
                        details.append(f"{hours}hrs")
                    if rate:
                        details.append(f"@ ${rate}/hr")
                    if this_period:
                        details.append(f"This Period: ${this_period}")
                    if ytd:
                        details.append(f"YTD: ${ytd}")
                    
                    detail_str = " | ".join(details) if details else f"${this_period}" if this_period else "Amount not specified"
                    earnings.append(f"  {idx}. {item_type}: {detail_str}")
        
        # Also check for individual earning fields (fallback)
        earning_fields = ['base_income', 'overtime', 'allowances', 'bonus', 'commission']
        for field in earning_fields:
            if field in payslip_data and payslip_data[field]:
                earnings.append(f"  - {field.replace('_', ' ').title()}: ${payslip_data[field]}")
        
        # Check raw_fields for any additional earning data
        if 'raw_fields' in payslip_data:
            raw_fields = payslip_data['raw_fields']
            # Look for any earning-related fields that might not be in the structured array
            for key, value in raw_fields.items():
                if 'earning' in key.lower() and key not in ['earning_items', 'earning_item']:
                    if isinstance(value, dict):
                        val = value.get('value', value)
                    else:
                        val = value
                    if val and str(val).strip():
                        earnings.append(f"  - {key}: {val}")
        
        return '\n'.join(earnings) if earnings else "  No detailed earnings breakdown available"
    
    def _format_deduction_items(self, payslip_data: Dict[str, Any]) -> str:
        """Format deduction items for better readability - shows ALL items with complete details"""
        deductions = []
        
        # Check for deduction_items array (structured from Document AI)
        if 'deduction_items' in payslip_data and payslip_data['deduction_items']:
            for idx, item in enumerate(payslip_data['deduction_items'], 1):
                if isinstance(item, dict):
                    item_type = item.get('type', item.get('description', 'Unknown'))
                    this_period = item.get('this_period', item.get('deduction_this_period', 0))
                    ytd = item.get('ytd', item.get('deduction_ytd', None))
                    
                    # Format with all available details
                    details = []
                    if this_period:
                        details.append(f"This Period: ${this_period}")
                    if ytd:
                        details.append(f"YTD: ${ytd}")
                    
                    detail_str = " | ".join(details) if details else f"${this_period}" if this_period else "Amount not specified"
                    deductions.append(f"  {idx}. {item_type}: {detail_str}")
        
        # Check for superannuation_items array separately
        if 'superannuation_items' in payslip_data and payslip_data['superannuation_items']:
            for idx, item in enumerate(payslip_data['superannuation_items'], 1):
                if isinstance(item, dict):
                    item_type = item.get('type', item.get('description', 'Superannuation'))
                    this_period = item.get('this_period', item.get('superannuation_this_period', 0))
                    ytd = item.get('ytd', item.get('superannuation_ytd', None))
                    
                    details = []
                    if this_period:
                        details.append(f"This Period: ${this_period}")
                    if ytd:
                        details.append(f"YTD: ${ytd}")
                    
                    detail_str = " | ".join(details) if details else f"${this_period}" if this_period else "Amount not specified"
                    deductions.append(f"  Super {idx}. {item_type}: {detail_str}")
        
        # Check for tax_items array separately
        if 'tax_items' in payslip_data and payslip_data['tax_items']:
            for idx, item in enumerate(payslip_data['tax_items'], 1):
                if isinstance(item, dict):
                    item_type = item.get('type', item.get('description', 'Tax'))
                    this_period = item.get('this_period', item.get('tax_this_period', 0))
                    ytd = item.get('ytd', item.get('tax_ytd', None))
                    
                    details = []
                    if this_period:
                        details.append(f"This Period: ${this_period}")
                    if ytd:
                        details.append(f"YTD: ${ytd}")
                    
                    detail_str = " | ".join(details) if details else f"${this_period}" if this_period else "Amount not specified"
                    deductions.append(f"  Tax {idx}. {item_type}: {detail_str}")
        
        # Check for individual deduction fields (fallback)
        deduction_fields = ['tax_withheld', 'superannuation', 'salary_sacrifice']
        for field in deduction_fields:
            if field in payslip_data and payslip_data[field]:
                deductions.append(f"  - {field.replace('_', ' ').title()}: ${payslip_data[field]}")
        
        # Check raw_fields for any additional deduction data
        if 'raw_fields' in payslip_data:
            raw_fields = payslip_data['raw_fields']
            # Look for any deduction-related fields that might not be in the structured arrays
            for key, value in raw_fields.items():
                if any(term in key.lower() for term in ['deduction', 'super', 'tax']) and key not in ['deduction_items', 'deduction_item', 'superannuation_items', 'superannuation_item', 'tax_items', 'tax_item']:
                    if isinstance(value, dict):
                        val = value.get('value', value)
                    else:
                        val = value
                    if val and str(val).strip():
                        deductions.append(f"  - {key}: {val}")
        
        return '\n'.join(deductions) if deductions else "  No detailed deductions breakdown available"
    
    def _format_superannuation_items(self, payslip_data: Dict[str, Any]) -> str:
        """Format superannuation items separately for better visibility"""
        super_items = []
        
        # Check for superannuation_items array (structured from Document AI)
        if 'superannuation_items' in payslip_data and payslip_data['superannuation_items']:
            for idx, item in enumerate(payslip_data['superannuation_items'], 1):
                if isinstance(item, dict):
                    item_type = item.get('type', item.get('description', 'Superannuation'))
                    this_period = item.get('this_period', item.get('superannuation_this_period', 0))
                    ytd = item.get('ytd', item.get('superannuation_ytd', None))
                    
                    details = []
                    if this_period:
                        details.append(f"This Period: ${this_period}")
                    if ytd:
                        details.append(f"YTD: ${ytd}")
                    
                    detail_str = " | ".join(details) if details else f"${this_period}" if this_period else "Amount not specified"
                    super_items.append(f"  {idx}. {item_type}: {detail_str}")
        
        # Also check for standalone superannuation field
        if 'superannuation' in payslip_data and payslip_data['superannuation']:
            super_items.append(f"  - Superannuation (summary): ${payslip_data['superannuation']}")
        
        return '\n'.join(super_items) if super_items else "  No superannuation items found"
    
    def _format_tax_items(self, payslip_data: Dict[str, Any]) -> str:
        """Format tax items separately for better visibility"""
        tax_items_list = []
        
        # Check for tax_items array (structured from Document AI)
        if 'tax_items' in payslip_data and payslip_data['tax_items']:
            for idx, item in enumerate(payslip_data['tax_items'], 1):
                if isinstance(item, dict):
                    item_type = item.get('type', item.get('description', 'Tax'))
                    this_period = item.get('this_period', item.get('tax_this_period', 0))
                    ytd = item.get('ytd', item.get('tax_ytd', None))
                    
                    details = []
                    if this_period:
                        details.append(f"This Period: ${this_period}")
                    if ytd:
                        details.append(f"YTD: ${ytd}")
                    
                    detail_str = " | ".join(details) if details else f"${this_period}" if this_period else "Amount not specified"
                    tax_items_list.append(f"  {idx}. {item_type}: {detail_str}")
        
        # Also check for standalone tax field
        if 'tax_withheld' in payslip_data and payslip_data['tax_withheld']:
            tax_items_list.append(f"  - Tax Withheld (summary): ${payslip_data['tax_withheld']}")
        
        return '\n'.join(tax_items_list) if tax_items_list else "  No tax items found"
    
    def _generate_fallback_policy_analysis(self, policy_name: str, document_data: Dict[str, Any]) -> str:
        """Generate a fallback policy analysis when AI is unavailable"""
        relevant_keys = []
        
        # Find relevant keys in the document data based on policy name
        policy_lower = policy_name.lower()
        for key in document_data:
            if any(term in key.lower() for term in policy_lower.split()):
                relevant_keys.append(key)
        
        if relevant_keys:
            values = [f"{k}: {document_data.get(k)}" for k in relevant_keys]
            return f"Found relevant information: {', '.join(values)}. Further verification may be needed to fully assess compliance with {policy_name} policy."
        else:
            return f"No direct information found for {policy_name} policy. Further verification from additional documents is recommended."
    
    def _generate_fallback_summary(self, processed_docs: List[Dict[str, Any]], 
                                  validation_results: Dict[str, Any]) -> str:
        summary_parts = []
        summary_parts.append("APPLICATION SUMMARY")
        summary_parts.append("=" * 50)
        
        summary_parts.append(f"\nDocuments Processed: {len(processed_docs)}")
        for doc in processed_docs:
            summary_parts.append(f"  - {doc.get('document_type', 'Unknown')}: {doc.get('filename')}")
        
        val_summary = validation_results.get('summary', {})
        summary_parts.append(f"\nValidation Results:")
        summary_parts.append(f"  Total Checks: {val_summary.get('total_checks', 0)}")
        summary_parts.append(f"  Passed: {val_summary.get('passed', 0)}")
        summary_parts.append(f"  Failed: {val_summary.get('failed', 0)}")
        summary_parts.append(f"  Warnings: {val_summary.get('warnings', 0)}")
        
        if val_summary.get('failed', 0) > 0:
            summary_parts.append("\nATTENTION REQUIRED: Some validation checks failed.")
        else:
            summary_parts.append("\nAll validation checks passed successfully.")
        
        return "\n".join(summary_parts)
