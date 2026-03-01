import logging
import re
import os
import csv
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dateutil import parser as date_parser
from services.gemini_service import GeminiService

logger = logging.getLogger(__name__)

class ValidationEngine:
    def __init__(self):
        self.CFG_FRESHNESS_DAYS = 60
        self.MIN_TENURE_FULL_TIME = 6
        self.MIN_TENURE_CASUAL = 12
        self.MIN_INCOME_THRESHOLD = 4000
        self.gemini_service = GeminiService()
        self.policy_details = self._load_policy_details()
        self.policy_config = self._load_policy_config()
        
    def _load_policy_details(self) -> Dict[str, str]:
        """Load policy details from CSV file"""
        policy_details = {}
        policy_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                  'PAYG Policy Checks - Sheet2.csv')
        
        try:
            with open(policy_file, 'r') as f:
                reader = csv.reader(f)
                next(reader)  # Skip header
                for row in reader:
                    if len(row) >= 3 and row[1]:  # Check if policy name exists
                        policy_details[row[1].strip()] = row[2] if len(row) > 2 else ""
        except Exception as e:
            logger.warning(f"Could not load policy details: {e}")
        
        return policy_details
    
    def _load_policy_config(self) -> Dict[str, Any]:
        """Load policy configuration from payg_policy_config.json"""
        policy_config = {}
        config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                   'payg_policy_config.json')
        
        try:
            with open(config_file, 'r') as f:
                policy_config = json.load(f)
            logger.info("Successfully loaded payg_policy_config.json")
        except Exception as e:
            logger.warning(f"Could not load policy config: {e}")
        
        return policy_config
    
    def validate_application(self, processed_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        payslips = [doc for doc in processed_docs if doc.get('document_type') == 'payslip']
        bank_statements = [doc for doc in processed_docs if doc.get('document_type') == 'bank_statement']
        
        validation_results = {
            'checks': [],
            'summary': {
                'total_checks': 0,
                'passed': 0,
                'failed': 0,
                'warnings': 0,
                'not_applicable': 0
            },
            'exceptions': [],
            'extracted_summary': {}
        }
        
        # Organize checks into their respective categories
        if payslips:
            payslip_checks = self._validate_payslips(payslips)
            validation_results['payslip_checks'] = payslip_checks
            validation_results['checks'].extend(payslip_checks)
        
        if bank_statements:
            bank_checks = self._validate_bank_statements(bank_statements)
            validation_results['bank_statement_checks'] = bank_checks
            validation_results['checks'].extend(bank_checks)
        
        if payslips and bank_statements:
            cross_checks = self._cross_validate_documents(payslips, bank_statements)
            validation_results['cross_validation_checks'] = cross_checks
            validation_results['checks'].extend(cross_checks)
        
        # Add document completeness checks to general checks
        completeness_checks = self._validate_document_completeness(processed_docs)
        validation_results['checks'].extend(completeness_checks)
        
        # Add PAYG policy checks
        payg_policy_results = self._validate_payg_policies(payslips, bank_statements)
        validation_results['payg_policy_checks'] = payg_policy_results
        validation_results['checks'].extend(payg_policy_results['checks'])
        
        for check in validation_results['checks']:
            validation_results['summary']['total_checks'] += 1
            if check['status'] == 'pass':
                validation_results['summary']['passed'] += 1
            elif check['status'] == 'fail':
                validation_results['summary']['failed'] += 1
            elif check['status'] == 'warning':
                validation_results['summary']['warnings'] += 1
            elif check['status'] == 'not_applicable':
                validation_results['summary']['not_applicable'] += 1
            
            if check.get('exception_code'):
                validation_results['exceptions'].append({
                    'code': check['exception_code'],
                    'message': check['message'],
                    'severity': check['status']
                })
        
        validation_results['extracted_summary'] = self._extract_summary_data(payslips, bank_statements)
        
        return validation_results
    
    def _validate_payslips(self, payslips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        checks = []
        
        for idx, doc in enumerate(payslips):
            data = doc.get('extracted_data', {})
            
            checks.append(self._create_check(
                f"Payslip #{idx+1}: Employee Name Present",
                bool(data.get('employee_name')),
                f"Employee name: {data.get('employee_name', 'NOT FOUND')}",
                data.get('confidence', 0.0),
                "FIELD_EMPLOYEE_NAME",
                "EXC_PAYSLIP_INCOMPLETE" if not data.get('employee_name') else None
            ))
            
            checks.append(self._create_check(
                f"Payslip #{idx+1}: Employer Name Present",
                bool(data.get('employer_name')),
                f"Employer: {data.get('employer_name', 'NOT FOUND')}",
                data.get('confidence', 0.0),
                "FIELD_EMPLOYER_NAME",
                "EXC_PAYSLIP_INCOMPLETE" if not data.get('employer_name') else None
            ))
            
            checks.append(self._create_check(
                f"Payslip #{idx+1}: ABN Present",
                bool(data.get('abn')),
                f"ABN: {data.get('abn', 'None')}",
                data.get('confidence', 0.0),
                "FIELD_ABN"
            ))
            
            # Updated to use start_date and end_date instead of pay_period_start/end
            checks.append(self._create_check(
                f"Payslip #{idx+1}: Pay Period Defined",
                bool(data.get('start_date') or data.get('end_date')),
                f"Pay Period: {data.get('start_date', 'N/A')} to {data.get('end_date', 'N/A')}",
                data.get('confidence', 0.0),
                "FIELD_PAY_PERIOD",
                "EXC_PAYSLIP_INCOMPLETE" if not (data.get('start_date') or data.get('end_date')) else None
            ))
            
            gross = data.get('gross_pay')
            net = data.get('net_pay')
            
            if gross and net:
                try:
                    # Convert string values with currency symbols and commas to float
                    gross_float = float(re.sub(r'[^\d.]', '', gross.replace(',', ''))) if isinstance(gross, str) else float(gross)
                    net_float = float(re.sub(r'[^\d.]', '', net.replace(',', ''))) if isinstance(net, str) else float(net)
                    
                    logical_check = net_float <= gross_float
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error comparing gross and net pay: {e}")
                    logical_check = True  # Default to passing if we can't compare
                gross_str = f"${gross}" if gross is not None else "N/A"
                net_str = f"${net}" if net is not None else "N/A"
                checks.append(self._create_check(
                    f"Payslip #{idx+1}: Net Pay ≤ Gross Pay",
                    logical_check,
                    f"Gross: {gross_str}, Net: {net_str}",
                    data.get('confidence', 0.0),
                    "FIELD_GROSS_NET_LOGIC"
                ))
            
            # Format gross and net values properly based on their type
            if gross is not None:
                gross_str = f"${gross}" if isinstance(gross, str) else f"${float(gross):.2f}"
            else:
                gross_str = "NOT FOUND"
                
            if net is not None:
                net_str = f"${net}" if isinstance(net, str) else f"${float(net):.2f}"
            else:
                net_str = "NOT FOUND"
            
            # Check for gross_earnings field first, then fall back to gross_pay
            gross_earnings = data.get('gross_earnings')
            if gross_earnings is not None:
                gross = gross_earnings
                gross_str = f"${gross_earnings}" if isinstance(gross_earnings, str) else f"${float(gross_earnings):.2f}"
                
            checks.append(self._create_check(
                f"Payslip #{idx+1}: Gross Pay Present",
                bool(gross),
                f"Gross Pay: {gross_str}",
                data.get('confidence', 0.0),
                "FIELD_GROSS"
            ))
            
            checks.append(self._create_check(
                f"Payslip #{idx+1}: Net Pay Present",
                bool(net),
                f"Net Pay: {net_str}",
                data.get('confidence', 0.0),
                "FIELD_NET"
            ))
            
            pay_date = data.get('pay_date')
            if pay_date:
                freshness = self._check_date_freshness(pay_date)
                checks.append(self._create_check(
                    f"Payslip #{idx+1}: Document Freshness (≤{self.CFG_FRESHNESS_DAYS} days)",
                    freshness['is_fresh'],
                    freshness['message'],
                    0.9,
                    "FRESHNESS_CHECK",
                    "EXC_FRESHNESS" if not freshness['is_fresh'] else None
                ))
        
        return checks
    
    def _validate_bank_statements(self, bank_statements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        checks = []
        
        for idx, doc in enumerate(bank_statements):
            data = doc.get('extracted_data', {})
            
            # Basic field presence checks
            checks.append(self._create_check(
                f"Bank Statement #{idx+1}: Account Holder Name Present",
                bool(data.get('account_holder')),
                f"Account Holder: {data.get('account_holder', 'NOT FOUND')}",
                data.get('confidence', 0.0),
                "FIELD_ACCOUNT_HOLDER"
            ))
            
            checks.append(self._create_check(
                f"Bank Statement #{idx+1}: Account Number Present",
                bool(data.get('account_number')),
                f"Account: {data.get('account_number', 'NOT FOUND')}",
                data.get('confidence', 0.0),
                "FIELD_ACCOUNT_NUMBER"
            ))
            
            # BSB check
            checks.append(self._create_check(
                f"Bank Statement #{idx+1}: BSB Present",
                bool(data.get('bsb')),
                f"BSB: {data.get('bsb', 'NOT FOUND')}",
                data.get('confidence', 0.0),
                "FIELD_BSB"
            ))
            
            # Bank name check
            checks.append(self._create_check(
                f"Bank Statement #{idx+1}: Bank Name Present",
                bool(data.get('bank_name')),
                f"Bank: {data.get('bank_name', 'NOT FOUND')}",
                data.get('confidence', 0.0),
                "FIELD_BANK_NAME"
            ))
            
            # Statement period check
            has_period = bool(data.get('statement_period_start') or data.get('statement_period_end'))
            checks.append(self._create_check(
                f"Bank Statement #{idx+1}: Statement Period Defined",
                has_period,
                f"Period: {data.get('statement_period_start', 'N/A')} to {data.get('statement_period_end', 'N/A')}",
                data.get('confidence', 0.0),
                "FIELD_STATEMENT_PERIOD"
            ))
            
            # Transaction history check - look for transaction_items field
            transactions = data.get('transaction_items', data.get('transactions', []))
            has_transactions = bool(transactions and len(transactions) > 0)
            transaction_count = len(transactions)
            checks.append(self._create_check(
                f"Bank Statement #{idx+1}: Contains Transactions",
                has_transactions,
                f"Found {transaction_count} transactions",
                data.get('confidence', 0.0),
                "FIELD_TRANSACTIONS"
            ))
            
            opening = data.get('opening_balance')
            closing = data.get('closing_balance')
            
            # Format opening and closing balances properly based on their type
            if opening is not None:
                opening_str = f"${opening}" if isinstance(opening, str) else f"${float(opening):.2f}"
            else:
                opening_str = "N/A"
                
            if closing is not None:
                closing_str = f"${closing}" if isinstance(closing, str) else f"${float(closing):.2f}"
            else:
                closing_str = "N/A"
            
            checks.append(self._create_check(
                f"Bank Statement #{idx+1}: Balance Information Present",
                bool(opening or closing),
                f"Opening: {opening_str}, Closing: {closing_str}",
                data.get('confidence', 0.0),
                "FIELD_BALANCE"
            ))
            
            statement_end = data.get('statement_period_end')
            if statement_end:
                freshness = self._check_date_freshness(statement_end)
                checks.append(self._create_check(
                    f"Bank Statement #{idx+1}: Statement Freshness (≤{self.CFG_FRESHNESS_DAYS} days)",
                    freshness['is_fresh'],
                    freshness['message'],
                    0.9,
                    "FRESHNESS_CHECK",
                    "EXC_FRESHNESS" if not freshness['is_fresh'] else None
                ))
            
            # Check for salary deposits in the updated field name
            salary_deposits = data.get('salary_deposits', [])
            checks.append(self._create_check(
                f"Bank Statement #{idx+1}: Salary Deposits Identified",
                len(salary_deposits) > 0,
                f"Found {len(salary_deposits)} potential salary deposit(s)",
                0.7,
                "SALARY_DEPOSITS"
            ))
        
        return checks
    
    def _cross_validate_documents(self, payslips: List[Dict[str, Any]], 
                                  bank_statements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        checks = []
        
        if not payslips or not bank_statements:
            return checks
            
        # Extract key information from payslips
        payslip_names = set()
        payslip_employers = set()
        total_payslip_income = 0
        
        for payslip in payslips:
            data = payslip.get('extracted_data', {})
            if data.get('employee_name'):
                payslip_names.add(data.get('employee_name').upper())
            if data.get('employer_name'):
                payslip_employers.add(data.get('employer_name').lower())
            if data.get('net_pay'):
                try:
                    net_pay = data.get('net_pay')
                    if isinstance(net_pay, str):
                        net_pay = float(net_pay.replace(',', ''))
                    total_payslip_income += net_pay
                except (ValueError, TypeError):
                    pass
        
        # Extract key information from bank statements
        bank_names = set()
        employer_deposits = []
        
        for statement in bank_statements:
            data = statement.get('extracted_data', {})
            if data.get('account_holder'):
                bank_names.add(data.get('account_holder').upper())
            
            # Look for deposits that might match employer names
            for transaction in data.get('transactions', []):
                if transaction.get('type') == 'credit' and transaction.get('amount'):
                    description = transaction.get('description', '').lower()
                    for employer in payslip_employers:
                        if employer in description or any(word in description for word in employer.split()):
                            employer_deposits.append({
                                'employer': employer,
                                'amount': transaction.get('amount'),
                                'date': transaction.get('date'),
                                'description': transaction.get('description')
                            })
        
        # Name matching check
        latest_payslip = payslips[0].get('extracted_data', {}) or {}
        latest_bank = bank_statements[0].get('extracted_data', {}) or {}
        
        payslip_name = latest_payslip.get('employee_name', '') or ''
        bank_name = latest_bank.get('account_holder', '') or ''
        
        # Convert to uppercase only if not empty
        payslip_name = payslip_name.upper() if payslip_name else ''
        bank_name = bank_name.upper() if bank_name else ''
        
        if payslip_name and bank_name:
            name_match = payslip_name in bank_name or bank_name in payslip_name
            checks.append(self._create_check(
                "Cross-check: Name Matching (Payslip ↔ Bank Statement)",
                name_match,
                f"Payslip: {payslip_name}, Bank: {bank_name}",
                0.8,
                "CROSS_NAME_MATCH",
                "EXC_NAME_MISMATCH" if not name_match else None
            ))
        
        # Income verification check
        net_pay = latest_payslip.get('net_pay')
        salary_deposits = latest_bank.get('salary_deposits', [])
        
        if net_pay and salary_deposits:
            # Convert net_pay to float if it's a string
            net_pay_float = float(net_pay.replace(',', '')) if isinstance(net_pay, str) else float(net_pay)
            
            matching_deposit = any(
                abs(deposit.get('amount', 0) - net_pay_float) < 50
                for deposit in salary_deposits
            )
            
            # Format net_pay properly based on its type
            if isinstance(net_pay, str):
                net_pay_str = f"${net_pay}"
            else:
                net_pay_str = f"${float(net_pay):.2f}"
                
            checks.append(self._create_check(
                "Cross-check: Net Pay Amount ↔ Bank Deposit",
                matching_deposit,
                f"Net Pay: {net_pay_str}, Deposits found: {len(salary_deposits)}",
                0.7,
                "CROSS_AMOUNT_MATCH",
                "EXC_AMOUNT_MISMATCH" if not matching_deposit else None
            ))
        
        # Employer consistency check
        if employer_deposits and payslip_employers:
            deposit_employers = set(d['employer'] for d in employer_deposits)
            common_employers = deposit_employers.intersection(payslip_employers)
            
            employer_consistent = len(common_employers) > 0
            if employer_consistent:
                employer_details = f"Matching employers: {', '.join(common_employers)}"
            else:
                employer_details = "No matching employers between payslips and bank deposits"
                
            checks.append(self._create_check(
                "Cross-check: Employer Consistency",
                employer_consistent,
                employer_details,
                0.8,
                "CROSS_EMPLOYER_CONSISTENCY",
                "EXC_EMPLOYER_MISMATCH" if not employer_consistent else None
            ))
        
        return checks
    
    def _validate_document_completeness(self, processed_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        checks = []
        
        doc_types = [doc.get('document_type') for doc in processed_docs]
        
        has_payslip = 'payslip' in doc_types
        has_bank = 'bank_statement' in doc_types
        
        checks.append(self._create_check(
            "Document Completeness: Payslip Provided",
            has_payslip,
            "At least one payslip is required for PAYG verification",
            1.0,
            "DOC_COMPLETENESS",
            "EXC_MISSING_PAYSLIP" if not has_payslip else None
        ))
        
        checks.append(self._create_check(
            "Document Completeness: Bank Statement Provided",
            has_bank,
            "Bank statement required for income verification",
            1.0,
            "DOC_COMPLETENESS",
            "EXC_MISSING_BANK" if not has_bank else None
        ))
        
        payslip_count = doc_types.count('payslip')
        checks.append(self._create_check(
            "Document Completeness: Minimum 2 Consecutive Payslips (Preferred)",
            payslip_count >= 2,
            f"Provided {payslip_count} payslip(s). 2+ consecutive payslips preferred.",
            0.8,
            "DOC_COMPLETENESS"
        ))
        
        return checks
    
    def _validate_payg_policies(self, payslips: List[Dict[str, Any]], bank_statements: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate PAYG policies based on the 18 policy checks defined in the requirements.
        Uses Vertex AI (Gemini) for intelligent analysis with full payslip context.
        OPTIMIZED: Makes a single batched AI call for all 18 policies to avoid quota limits.
        Returns a dictionary with policy check results.
        """
        try:
            results = {
                'checks': [],
                'summary': {
                    'total_checks': 18,
                    'passed': 0,
                    'failed': 0,
                    'warnings': 0,
                    'not_applicable': 0
                }
            }
            
            # Defensive check for payslips
            if not payslips:
                results['summary']['not_applicable'] = 18
                return results
                
            # Extract payslip data with defensive programming
            latest_payslip = {}
            try:
                if payslips and isinstance(payslips[0], dict):
                    latest_payslip = payslips[0].get('extracted_data', {}) or {}
            except (IndexError, AttributeError, TypeError) as e:
                logger.error(f"Error extracting latest payslip: {e}")
            
            # Prepare comprehensive document data for AI analysis
            document_data = {
                'payslip': latest_payslip,
                'all_payslips': [p.get('extracted_data', {}) for p in payslips if isinstance(p, dict)],
                'bank_statements': [],
                'payslip_count': len(payslips),
                'bank_statement_count': len(bank_statements) if bank_statements else 0
            }
            
            # Safely extract bank statement data
            if bank_statements:
                try:
                    document_data['bank_statements'] = [
                        bs.get('extracted_data', {}) for bs in bank_statements 
                        if isinstance(bs, dict) and 'extracted_data' in bs
                    ]
                except Exception as e:
                    logger.error(f"Error processing bank statements: {e}")
            
            # Load all policy details for context
            all_policies = getattr(self, 'policy_details', {}) or {}
            
            # Define the 18 main PAYG policy checks
            policy_checks = [
                ("PAYG Income\n (tenure)", "PAYG Income (tenure)"),
                ("Base income (100%)", "Base income (100%)"),
                ("Casual income \n (100%)", "Casual income (100%)"),
                ("Second Job (100%)", "Second Job (100%)"),
                ("Overtime / shift \n allowance (80%)", "Overtime / shift allowance (80%)"),
                ("Bonus/Commission \n (80%)", "Bonus/Commission (80%)"),
                ("Fully Maintained Car \n Benefits (100%)", "Fully Maintained Car Benefits (100%)"),
                ("Allowances (80%)", "Allowances (80%)"),
                ("Superannuation \n Contributions \n (Employer) (100%)", "Superannuation Contributions (Employer) (100%)"),
                ("Salary Sacrifice and \n Salary Packaging \n Arrangements \n (100%)", "Salary Sacrifice and Salary Packaging Arrangements (100%)"),
                ("Parental Leave \n (Employer or \n Government)", "Parental Leave (Employer or Government)"),
                ("PAYG \n Income \n Verification", "PAYG Income Verification"),
                ("Document\n requirements\n All dates are\n based on the\n date of\n submission", "Document requirements"),
                ("Pre-Tax Deduction", "Pre-Tax Deduction"),
                ("Post-Tax Deduction", "Post-Tax Deduction"),
                ("Tax", "Tax"),
                ("Net Pay and Gross Pay", "Net Pay and Gross Pay"),
                ("Non-income items", "Non-income items")
            ]
            
            # OPTIMIZATION: Batch all 18 policy checks into a single AI call
            logger.info("Analyzing all 18 PAYG policies in a single batched AI call...")
            
            try:
                # Make a single batched AI call for all policies
                batch_results = self._check_all_policies_batched(
                    policy_checks=policy_checks,
                    document_data=document_data,
                    all_policies=all_policies
                )
                
                results['checks'] = batch_results
                
            except Exception as e:
                logger.error(f"Error in batched policy analysis: {e}")
                # Fallback: Create warning results for all policies
                for policy_key, policy_name in policy_checks:
                    results['checks'].append(self._create_check(
                        policy_name,
                        False,
                        f"Error analyzing policies in batch: {str(e)}",
                        0.5,
                        f"POLICY_{policy_name.upper().replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'PCT')}",
                        None,
                        "warning"
                    ))
            
            # Update summary counts
            for check in results['checks']:
                status = check.get('status', '')
                if status == 'pass':
                    results['summary']['passed'] += 1
                elif status == 'fail':
                    results['summary']['failed'] += 1
                elif status == 'warning':
                    results['summary']['warnings'] += 1
                elif status == 'not_applicable':
                    results['summary']['not_applicable'] += 1
                    
            return results
            
        except Exception as e:
            # Catch-all exception handler to prevent app crashes
            logger.error(f"Error in _validate_payg_policies: {e}")
            return {
                'checks': [],
                'summary': {
                    'total_checks': 18,
                    'passed': 0,
                    'failed': 0,
                    'warnings': 0,
                    'not_applicable': 18
                }
            }
        
    def _check_all_policies_batched(self, policy_checks: List[tuple], 
                                     document_data: Dict[str, Any], 
                                     all_policies: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Check all 18 PAYG policies in a single batched AI call to avoid quota limits.
        This is much more efficient than making 18 separate API calls.
        """
        try:
            # Ensure Gemini service is available
            if not self.gemini_service.client_available:
                logger.error("Vertex AI is not available - this is required for policy checks!")
                return [
                    self._create_check(
                        policy_name,
                        False,
                        "ERROR: Vertex AI (Gemini) is not configured. Please check GCP_PROJECT_ID and credentials.",
                        0.0,
                        f"POLICY_{policy_name.upper().replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'PCT')}",
                        "EXC_AI_NOT_AVAILABLE",
                        "fail"
                    )
                    for _, policy_name in policy_checks
                ]
            
            # Use Vertex AI to analyze ALL policies in one call
            batch_analysis = self.gemini_service.analyze_all_policies_batched(
                policy_checks=policy_checks,
                document_data=document_data,
                all_policies=all_policies
            )
            
            # Parse the batch analysis into individual policy results
            results = []
            for policy_key, policy_name in policy_checks:
                # Extract the analysis for this specific policy from the batch result
                policy_analysis = self._extract_policy_from_batch(batch_analysis, policy_name)
                
                # Extract status from "**Status**: PASS/FAIL/WARNING/NOT_APPLICABLE"
                import re
                status_match = re.search(r'\*\*Status\*\*:\s*(PASS|FAIL|WARNING|NOT[_\s]APPLICABLE)', policy_analysis, re.IGNORECASE)
                
                if status_match:
                    status_text = status_match.group(1).upper().replace(' ', '_')
                    if 'PASS' in status_text:
                        status = 'pass'
                    elif 'FAIL' in status_text:
                        status = 'fail'
                    elif 'WARNING' in status_text:
                        status = 'warning'
                    elif 'NOT' in status_text or 'APPLICABLE' in status_text:
                        status = 'not_applicable'
                    else:
                        status = 'pass'
                else:
                    # Fallback: determine status based on keywords
                    analysis_lower = policy_analysis.lower()
                    if any(keyword in analysis_lower for keyword in ['not found', 'missing', 'not applicable', 'n/a']):
                        status = 'not_applicable'
                    elif any(keyword in analysis_lower for keyword in ['fail', 'does not meet', 'exceeds limit']):
                        status = 'fail'
                    elif any(keyword in analysis_lower for keyword in ['warning', 'further verification', 'additional']):
                        status = 'warning'
                    else:
                        status = 'pass'
                
                # Extract summary and details
                summary_match = re.search(r'\*\*Summary\*\*:\s*(.+?)(?=\*\*Additional Details\*\*|$)', policy_analysis, re.DOTALL | re.IGNORECASE)
                details_match = re.search(r'\*\*Additional Details\*\*:\s*(.+?)(?=##|$)', policy_analysis, re.DOTALL | re.IGNORECASE)
                
                summary = summary_match.group(1).strip() if summary_match else policy_analysis[:200]
                details = details_match.group(1).strip() if details_match else ""
                
                # Combine summary and details with separator
                if details:
                    message = f"{summary}\n\n**Additional Details:**\n{details}"
                else:
                    message = summary
                
                results.append(self._create_check(
                    policy_name,
                    status == 'pass',
                    message,
                    1.0,  # High confidence since it's AI-powered
                    f"POLICY_{policy_name.upper().replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'PCT')}",
                    None,
                    status
                ))
            
            return results
            
        except Exception as e:
            logger.error(f"Error in batched AI policy check: {e}")
            return [
                self._create_check(
                    policy_name,
                    False,
                    f"Error during batched AI analysis: {str(e)}. Please ensure Vertex AI is properly configured.",
                    0.0,
                    f"POLICY_{policy_name.upper().replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'PCT')}",
                    "EXC_AI_ERROR",
                    "fail"
                )
                for _, policy_name in policy_checks
            ]
    
    def _extract_policy_from_batch(self, batch_analysis: str, policy_name: str) -> str:
        """
        Extract the analysis for a specific policy from the batched AI response.
        """
        try:
            # Look for the policy section in the batch analysis
            # The AI response should have sections like "## 1. PAYG Income (tenure)"
            
            # Try to find the section for this policy
            import re
            
            # Create a pattern to match the policy section
            # Match patterns like "## 1. Policy Name" or "**1. Policy Name**"
            pattern = rf"(?:##|\*\*)\s*\d+\.\s*{re.escape(policy_name)}(?:\*\*)?[\s:]*\n(.*?)(?=(?:##|\*\*)\s*\d+\.|$)"
            
            match = re.search(pattern, batch_analysis, re.DOTALL | re.IGNORECASE)
            
            if match:
                return match.group(1).strip()
            
            # Fallback: Try simpler pattern
            pattern2 = rf"{re.escape(policy_name)}[\s:]*\n(.*?)(?=\n\n[A-Z]|$)"
            match2 = re.search(pattern2, batch_analysis, re.DOTALL | re.IGNORECASE)
            
            if match2:
                return match2.group(1).strip()
            
            # If we can't find the specific section, return a generic message
            return f"Analysis for {policy_name} is included in the comprehensive assessment. Please review the full analysis for details."
            
        except Exception as e:
            logger.error(f"Error extracting policy {policy_name} from batch: {e}")
            return f"Unable to extract specific analysis for {policy_name}. Please review the full assessment."
    
    def _check_policy_with_ai(self, policy_name: str, policy_details: str, 
                              document_data: Dict[str, Any], all_policies: Dict[str, str]) -> Dict[str, Any]:
        """
        Check a specific PAYG policy using Vertex AI with full payslip context.
        This ensures NO fallback - only Vertex AI is used for analysis.
        """
        try:
            # Ensure Gemini service is available
            if not self.gemini_service.client_available:
                logger.error("Vertex AI is not available - this is required for policy checks!")
                return self._create_check(
                    policy_name,
                    False,
                    "ERROR: Vertex AI (Gemini) is not configured. Please check GCP_PROJECT_ID and credentials.",
                    0.0,
                    f"POLICY_{policy_name.upper().replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'PCT')}",
                    "EXC_AI_NOT_AVAILABLE",
                    "fail"
                )
            
            # Use Vertex AI to analyze the policy with full context
            analysis = self.gemini_service.analyze_policy_check(
                policy_name=policy_name,
                document_data=document_data,
                policy_details=policy_details,
                all_policies=all_policies
            )
            
            # Determine status based on AI analysis
            # Look for keywords in the analysis to determine pass/fail/warning
            analysis_lower = analysis.lower()
            
            status = 'pass'
            if any(keyword in analysis_lower for keyword in ['not found', 'missing', 'not applicable', 'n/a', 'no evidence']):
                status = 'not_applicable'
            elif any(keyword in analysis_lower for keyword in ['fail', 'does not meet', 'exceeds limit', 'insufficient']):
                status = 'fail'
            elif any(keyword in analysis_lower for keyword in ['warning', 'further verification', 'additional', 'may need', 'recommend']):
                status = 'warning'
            
            return self._create_check(
                policy_name,
                status == 'pass',
                analysis,
                1.0,  # High confidence since it's AI-powered
                f"POLICY_{policy_name.upper().replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'PCT')}",
                None,
                status
            )
            
        except Exception as e:
            logger.error(f"Error in AI policy check for {policy_name}: {e}")
            return self._create_check(
                policy_name,
                False,
                f"Error during AI analysis: {str(e)}. Please ensure Vertex AI is properly configured.",
                0.0,
                f"POLICY_{policy_name.upper().replace(' ', '_').replace('(', '').replace(')', '').replace('%', 'PCT')}",
                "EXC_AI_ERROR",
                "fail"
            )
    
    def _determine_employment_type(self, payslip: Dict[str, Any]) -> str:
        """Determine employment type from payslip data"""
        try:
            # Default to empty string if not found
            employment_type = payslip.get('employment_type', '')
            
            # Check in earning items for casual indicators
            if payslip and 'earning_items' in payslip:
                for item in payslip.get('earning_items', []):
                    if not item:
                        continue
                    item_type = item.get('type', '')
                    if item_type and ('casual' in item_type.lower() or 'casual hours' in item_type.lower()):
                        return 'casual'
            
            # Check employee classification - Fix the AttributeError by handling None case
            classification = payslip.get('employee_classification', '')
            if classification is not None:
                classification = classification.lower()
                if 'casual' in classification:
                    return 'casual'
                elif 'probation' in classification:
                    return 'probation'
                elif 'full time' in classification or 'fulltime' in classification:
                    return 'full_time'
                elif 'part time' in classification or 'parttime' in classification:
                    return 'part_time'
                elif 'contract' in classification:
                    return 'contract'
        except Exception as e:
            # Catch any unexpected errors to prevent app crashes
            print(f"Error in _determine_employment_type: {e}")
            
        # Default return if no specific type is determined
        return 'unknown'
            
        # Default to full time if we can't determine
        return 'full_time'
    
    def _calculate_tenure(self, payslips: List[Dict[str, Any]], bank_statements: List[Dict[str, Any]]) -> int:
        """Calculate tenure in months based on payslips and bank statements"""
        # This is a simplified implementation - in a real system, we would analyze
        # bank statements to find consistent salary payments from the same employer
        
        # For now, just return the number of payslips as an approximation
        return len(payslips)
    
    def _check_payg_income_tenure(self, employment_type: str, tenure_months: int) -> Dict[str, Any]:
        """Check PAYG Income tenure policy"""
        status = 'fail'
        message = ''
        
        if employment_type in ['full_time', 'part_time', 'contract']:
            if tenure_months >= 3:
                status = 'pass'
                message = f"Employment type: {employment_type}. Tenure: {tenure_months} months. Meets minimum 3 months requirement."
            else:
                message = f"Employment type: {employment_type}. Tenure: {tenure_months} months. Does not meet minimum 3 months requirement."
        elif employment_type == 'casual':
            if tenure_months >= 6:
                status = 'pass'
                message = f"Employment type: Casual. Tenure: {tenure_months} months. Meets minimum 6 months requirement."
            else:
                message = f"Employment type: Casual. Tenure: {tenure_months} months. Does not meet minimum 6 months requirement."
        elif employment_type == 'probation':
            status = 'warning'
            message = "Employment type: Probation. Further verification needed as validation depends on letter from employer."
        else:
            message = f"Employment type: {employment_type}. Unable to determine tenure requirements."
        
        return self._create_check(
            "PAYG Income (tenure)",
            status == 'pass',
            message,
            0.8,
            "POLICY_PAYG_INCOME_TENURE",
            None,
            status
        )
    
    def _extract_base_income(self, payslip: Dict[str, Any]) -> float:
        """Extract base income from payslip"""
        try:
            # Try direct field first
            base_income = payslip.get('base_income', 0)
            if base_income:
                try:
                    if isinstance(base_income, str):
                        base_income = float(re.sub(r'[^\d.]', '', base_income.replace(',', '')))
                    return float(base_income)
                except (ValueError, TypeError):
                    pass
            
            # Look in earning items
            if payslip and 'earning_items' in payslip:
                for item in payslip.get('earning_items', []):
                    if not item:
                        continue
                    item_type = item.get('type', '')
                    if item_type and ('base' in item_type.lower() or 'salary' in item_type.lower() or 'ordinary' in item_type.lower()):
                        try:
                            amount = item.get('this_period', 0)
                            if isinstance(amount, str):
                                amount = float(re.sub(r'[^\d.]', '', amount.replace(',', '')))
                            return float(amount)
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            print(f"Error extracting base income: {e}")
        
        return 0.0
        
    def _extract_casual_income(self, payslip: Dict[str, Any]) -> float:
        """Extract casual income from payslip"""
        try:
            casual_income = 0
            
            # Look in earning items
            if payslip and 'earning_items' in payslip:
                for item in payslip.get('earning_items', []):
                    if not item:
                        continue
                    item_type = item.get('type', '')
                    if item_type and 'casual' in item_type.lower():
                        try:
                            amount = item.get('this_period', 0)
                            if isinstance(amount, str):
                                amount = float(re.sub(r'[^\d.]', '', amount.replace(',', '')))
                            casual_income += float(amount)
                        except (ValueError, TypeError):
                            pass
        
            # Check for casual hours
            
            return casual_income
        except Exception as e:
            print(f"Error extracting casual income: {e}")
            return 0.0
    
    def _check_base_income(self, base_income: float) -> Dict[str, Any]:
        """Check Base income policy"""
        status = 'pass' if base_income > 0 else 'warning'
        message = f"Base income: ${base_income:.2f}" if base_income > 0 else "Base income not found in payslip. Check if it's included under a different field name."
        
        # Add policy context from PAYG Policy Checks
        policy_context = "Base income is considered at 100% for servicing calculations."
        if base_income > 0:
            message = f"{message}. {policy_context}"
        
        return self._create_check(
            "Base income (100%)",
            status == 'pass',
            message,
            0.8,
            "POLICY_BASE_INCOME",
            None,
            status
        )
    
    def _extract_casual_income(self, payslip: Dict[str, Any]) -> float:
        """Extract casual income from payslip"""
        try:
            casual_income = 0
            
            # Look in earning items
            if payslip and 'earning_items' in payslip:
                for item in payslip.get('earning_items', []):
                    if not item:
                        continue
                    item_type = item.get('type', '')
                    if item_type and 'casual' in item_type.lower():
                        try:
                            amount = item.get('this_period', 0)
                            if isinstance(amount, str):
                                amount = float(re.sub(r'[^\d.]', '', amount.replace(',', '')))
                            casual_income += float(amount)
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            print(f"Error extracting casual income: {e}")
            return 0.0
        
        # Check for casual hours
        if casual_income == 0:
            casual_hours = payslip.get('casual_hours', 0)
            hourly_rate = payslip.get('hourly_rate', 0)
            if casual_hours and hourly_rate:
                try:
                    casual_income = float(casual_hours) * float(hourly_rate)
                except (ValueError, TypeError):
                    pass
        
        return casual_income
    
    def _check_casual_income(self, casual_income: float, employment_type: str) -> Dict[str, Any]:
        """Check Casual income policy"""
        if employment_type != 'casual':
            return self._create_check(
                "Casual income (100%)",
                True,
                "Not applicable - not casual employment",
                0.8,
                "POLICY_CASUAL_INCOME",
                None,
                "not_applicable"
            )
        
        status = 'pass' if casual_income > 0 else 'warning'
        message = f"Casual income: ${casual_income:.2f}" if casual_income > 0 else "Casual income not found in payslip"
        
        # Add policy context
        policy_context = "Casual income is considered at 100% for servicing calculations when the applicant has been employed for at least 6 months."
        if casual_income > 0:
            message = f"{message}. {policy_context}"
        
        return self._create_check(
            "Casual income (100%)",
            status == 'pass',
            message,
            0.8,
            "POLICY_CASUAL_INCOME",
            None,
            status
        )
    
    def _extract_second_job_income(self, payslip: Dict[str, Any]) -> float:
        """Extract second job income from payslip"""
        # This is a placeholder - in a real system, we would need to identify
        # if this is a second job based on application data
        return 0
    
    def _check_second_job(self, second_job_income: float, bank_statements: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check Second Job policy"""
        # This is a simplified implementation
        if second_job_income == 0:
            return self._create_check(
                "Second Job (100%)",
                True,
                "Not applicable - no second job income identified",
                0.8,
                "POLICY_SECOND_JOB",
                None,
                "not_applicable"
            )
        
        # In a real implementation, we would check bank statements for 6+ months of payments
        # and calculate total work hours
        
        return self._create_check(
            "Second Job (100%)",
            False,
            "Second job detected. Further verification needed to check tenure and total work hours.",
            0.8,
            "POLICY_SECOND_JOB",
            None,
            "warning"
        )
    
    def _extract_overtime_allowance(self, payslip: Dict[str, Any]) -> float:
        """Extract overtime/shift allowance from payslip"""
        overtime_allowance = 0
        
        # Look in earning items
        for item in payslip.get('earning_items', []):
            item_type = item.get('type', '').lower()
            if 'overtime' in item_type or 'shift' in item_type:
                try:
                    amount = item.get('this_period', 0)
                    if isinstance(amount, str):
                        amount = float(re.sub(r'[^\d.]', '', amount.replace(',', '')))
                    overtime_allowance += float(amount)
                except (ValueError, TypeError):
                    pass
        
        # Also check for direct overtime field
        if 'overtime' in payslip:
            try:
                overtime = payslip.get('overtime', 0)
                if isinstance(overtime, str):
                    overtime = float(re.sub(r'[^\d.]', '', overtime.replace(',', '')))
                overtime_allowance += float(overtime)
            except (ValueError, TypeError):
                pass
        
        return overtime_allowance
    
    def _check_overtime_allowance(self, overtime_allowance: float, payslips: List[Dict[str, Any]], document_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Check Overtime/shift allowance policy"""
        if overtime_allowance == 0:
            return self._create_check(
                "Overtime / shift allowance (80%)",
                True,
                "Not applicable - no overtime or shift allowance identified",
                0.8,
                "POLICY_OVERTIME_ALLOWANCE",
                None,
                "not_applicable"
            )
        
        # Check if we have 6+ months of YTD data
        has_ytd_data = False
        for payslip in payslips:
            data = payslip.get('extracted_data', {})
            if data.get('gross_earnings_ytd') or data.get('ytd_gross_earnings'):
                has_ytd_data = True
                break
        
        if has_ytd_data:
            return self._create_check(
                "Overtime / shift allowance (80%)",
                True,
                f"Overtime/shift allowance: ${overtime_allowance:.2f}. YTD data available. Overtime/shift allowances are considered at 80% for servicing calculations when supported by 6+ months of YTD data.",
                0.8,
                "POLICY_OVERTIME_ALLOWANCE",
                None,
                "pass"
            )
        else:
            return self._create_check(
                "Overtime / shift allowance (80%)",
                False,
                f"Overtime/shift allowance: ${overtime_allowance:.2f}. Further verification needed as validation depends on Tax return, Income Statement or Payment Summary. Overtime/shift allowances are considered at 80% for servicing calculations when properly verified.",
                0.8,
                "POLICY_OVERTIME_ALLOWANCE",
                None,
                "warning"
            )
    
    def _extract_bonus_commission(self, payslip: Dict[str, Any]) -> float:
        """Extract bonus/commission from payslip"""
        bonus_commission = 0
        
        # Look in earning items
        for item in payslip.get('earning_items', []):
            item_type = item.get('type', '').lower()
            if 'bonus' in item_type or 'commission' in item_type:
                try:
                    bonus_commission += float(item.get('this_period', 0))
                except (ValueError, TypeError):
                    pass
        
        return bonus_commission
    
    def _check_bonus_commission(self, bonus_commission: float, base_income: float, payslips: List[Dict[str, Any]], document_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Check Bonus/Commission policy"""
        if bonus_commission == 0:
            return self._create_check(
                "Bonus/Commission (80%)",
                True,
                "Not applicable - no bonus or commission identified",
                0.8,
                "POLICY_BONUS_COMMISSION",
                None,
                "not_applicable"
            )
        
        # Check if bonus/commission is no more than double base income
        if base_income > 0 and bonus_commission > (2 * base_income):
            return self._create_check(
                "Bonus/Commission (80%)",
                False,
                f"Bonus/Commission: ${bonus_commission:.2f}. Exceeds double the base income (${base_income:.2f}).",
                0.8,
                "POLICY_BONUS_COMMISSION",
                None,
                "fail"
            )
        
        # In a real implementation, we would check for 12+ months of regular payments
        # or 2+ years for annual/irregular payments
        
        return self._create_check(
            "Bonus/Commission (80%)",
            False,
            f"Bonus/Commission: ${bonus_commission:.2f}. Further verification needed to check payment regularity and history.",
            0.8,
            "POLICY_BONUS_COMMISSION",
            None,
            "warning"
        )
    
    def _extract_car_benefits(self, payslip: Dict[str, Any]) -> float:
        """Extract car benefits from payslip"""
        car_benefits = 0
        
        # Look in earning items
        for item in payslip.get('earning_items', []):
            item_type = item.get('type', '').lower()
            if 'car' in item_type and ('benefit' in item_type or 'allowance' in item_type):
                try:
                    car_benefits += float(item.get('this_period', 0))
                except (ValueError, TypeError):
                    pass
        
        return car_benefits
    
    def _check_car_benefits(self, car_benefits: float, document_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Check Fully Maintained Car Benefits policy"""
        if car_benefits == 0:
            return self._create_check(
                "Fully Maintained Car Benefits (100%)",
                True,
                "Not applicable - no car benefits identified",
                0.8,
                "POLICY_CAR_BENEFITS",
                None,
                "not_applicable"
            )
        
        # Check if car benefits exceed $3,500 per annum
        # This is a simplified calculation - in a real system, we would annualize the amount
        annual_car_benefits = car_benefits * 26  # Assuming fortnightly pay
        
        if annual_car_benefits > 3500:
            return self._create_check(
                "Fully Maintained Car Benefits (100%)",
                True,
                f"Car benefits: ${car_benefits:.2f} (estimated ${annual_car_benefits:.2f} annually). Exceeds $3,500 limit - only $3,500 can be included in loan serviceability.",
                0.8,
                "POLICY_CAR_BENEFITS",
                None,
                "warning"
            )
        
        return self._create_check(
            "Fully Maintained Car Benefits (100%)",
            True,
            f"Car benefits: ${car_benefits:.2f} (estimated ${annual_car_benefits:.2f} annually). Within $3,500 annual limit.",
            0.8,
            "POLICY_CAR_BENEFITS",
            None,
            "pass"
        )
    
    def _extract_allowances(self, payslip: Dict[str, Any]) -> float:
        """Extract allowances from payslip"""
        allowances = 0
        
        # Look in earning items
        for item in payslip.get('earning_items', []):
            item_type = item.get('type', '').lower()
            if 'allowance' in item_type and 'car' not in item_type:
                try:
                    allowances += float(item.get('this_period', 0))
                except (ValueError, TypeError):
                    pass
        
        return allowances
    
    def _check_allowances(self, allowances: float, base_income: float, document_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Check Allowances policy"""
        if allowances == 0:
            return self._create_check(
                "Allowances (80%)",
                True,
                "Not applicable - no allowances identified",
                0.8,
                "POLICY_ALLOWANCES",
                None,
                "not_applicable"
            )
        
        # Check if allowances exceed 25% of base income
        if base_income > 0 and allowances > (0.25 * base_income):
            return self._create_check(
                "Allowances (80%)",
                False,
                f"Allowances: ${allowances:.2f}. Exceeds 25% of base income (${base_income:.2f}).",
                0.8,
                "POLICY_ALLOWANCES",
                None,
                "fail"
            )
        
        return self._create_check(
            "Allowances (80%)",
            True,
            f"Allowances: ${allowances:.2f}. Within 25% of base income (${base_income:.2f}).",
            0.8,
            "POLICY_ALLOWANCES",
            None,
            "pass"
        )
    
    def _extract_salary_sacrifice(self, payslip: Dict[str, Any]) -> Dict[str, Any]:
        """Extract salary sacrifice from payslip"""
        result = {
            'amount': 0,
            'details': []
        }
        
        # Look in deduction items
        for item in payslip.get('deduction_items', []):
            item_type = item.get('type', '').lower() if isinstance(item.get('type'), str) else ''
            if any(keyword in item_type for keyword in ['salary sacrifice', 'salary packaging', 'super', 'superannuation']):
                try:
                    amount = item.get('this_period', 0)
                    if isinstance(amount, str):
                        amount = float(re.sub(r'[^\d.]', '', amount.replace(',', '')))
                    result['amount'] += float(amount)
                    result['details'].append({
                        'type': item.get('type', ''),
                        'amount': amount
                    })
                except (ValueError, TypeError):
                    pass
        
        # Check for superannuation summary
        if 'superannuation' in payslip:
            try:
                super_amount = payslip.get('superannuation', 0)
                if isinstance(super_amount, str):
                    super_amount = float(re.sub(r'[^\d.]', '', super_amount.replace(',', '')))
                result['amount'] += float(super_amount)
                result['details'].append({
                    'type': 'Superannuation',
                    'amount': super_amount
                })
            except (ValueError, TypeError):
                pass
        
        return result
    
    def _check_salary_sacrifice(self, salary_sacrifice_data: Dict[str, Any], document_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Check Salary Sacrifice and Salary Packaging Arrangements policy"""
        amount = salary_sacrifice_data.get('amount', 0)
        details = salary_sacrifice_data.get('details', [])
        
        policy_name = "Salary Sacrifice and Salary Packaging Arrangements (100%)"
        policy_details = self.policy_details.get(policy_name, "")
        
        # Check for superannuation in payslip even if no explicit salary sacrifice amount
        has_super = False
        super_amount = 0
        
        if document_data and 'payslip' in document_data:
            payslip_data = document_data.get('payslip', {})
            # Look for superannuation-related keys in the payslip
            for key, value in payslip_data.items():
                if any(term in key.lower() for term in ['super', 'superannuation', 'retirement']):
                    has_super = True
                    if isinstance(value, (int, float)):
                        super_amount = value
                    elif isinstance(value, dict) and 'amount' in value:
                        super_amount = value.get('amount', 0)
                    break
        
        # If we found superannuation but no explicit salary sacrifice amount, set amount to super_amount
        if has_super and amount == 0:
            amount = super_amount
            salary_sacrifice_data['superannuation'] = {'amount': super_amount}
        
        # Use Vertex AI for intelligent analysis if document data is available
        if document_data and (amount > 0 or has_super):
            analysis = self.gemini_service.analyze_policy_check(
                policy_name, 
                {
                    'salary_sacrifice': salary_sacrifice_data,
                    'payslip': document_data.get('payslip', {}),
                    'has_superannuation': has_super,
                    'superannuation_amount': super_amount
                },
                policy_details,
                self.policy_details  # Pass all policies for context
            )
            
            # If analysis is successful, return it as the result
            if analysis:
                return self._create_check(
                    policy_name,
                    True,
                    analysis,
                    1.0,  # 100% for servicing calculations
                    "POLICY_SALARY_SACRIFICE",
                    None,
                    "pass"
                )
            
            return self._create_check(
                policy_name,
                True,
                analysis,
                0.8,
                "POLICY_SALARY_SACRIFICE",
                None,
                "pass" if amount > 0 else "warning"
            )
        
        if amount == 0:
            return self._create_check(
                policy_name,
                True,
                "Not applicable - no salary sacrifice or packaging arrangements identified",
                0.8,
                "POLICY_SALARY_SACRIFICE",
                None,
                "not_applicable"
            )
        
        # Create detailed message with superannuation summary
        detail_text = ""
        if details:
            detail_text = " Details: " + ", ".join([f"{d.get('type')}: ${float(d.get('amount', 0)):.2f}" for d in details])
        
        return self._create_check(
            policy_name,
            True,
            f"Salary sacrifice and packaging arrangements: ${amount:.2f}.{detail_text} Salary sacrifice arrangements are considered at 100% for servicing calculations when properly verified. Further verification may be needed from employer to confirm these arrangements can be converted to cash.",
            0.8,
            "POLICY_SALARY_SACRIFICE",
            None,
            "pass" if amount > 0 else "warning"
        )
    
    def _extract_parental_leave(self, payslip: Dict[str, Any]) -> float:
        """Extract parental leave from payslip"""
        parental_leave = 0
        
        # Look in earning items
        for item in payslip.get('earning_items', []):
            item_type = item.get('type', '').lower()
            if 'parental' in item_type or 'maternity' in item_type or 'paternity' in item_type:
                try:
                    parental_leave += float(item.get('this_period', 0))
                except (ValueError, TypeError):
                    pass
        
        return parental_leave
    
    def _check_parental_leave(self, parental_leave: float, document_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Check Parental Leave policy"""
        if parental_leave == 0:
            return self._create_check(
                "Parental Leave (Employer or Government)",
                True,
                "Not applicable - no parental leave identified",
                0.8,
                "POLICY_PARENTAL_LEAVE",
                None,
                "not_applicable"
            )
        
        return self._create_check(
            "Parental Leave (Employer or Government)",
            False,
            f"Parental leave: ${parental_leave:.2f}. Further verification needed as validation depends on letter from employer.",
            0.8,
            "POLICY_PARENTAL_LEAVE",
            None,
            "warning"
        )
    
    def _check_payg_income_verification(self, payslips: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check PAYG Income Verification policy"""
        if len(payslips) >= 2:
            return self._create_check(
                "PAYG Income Verification",
                True,
                f"Provided {len(payslips)} payslips, meeting the requirement of at least 2 payslips.",
                0.8,
                "POLICY_PAYG_INCOME_VERIFICATION",
                None,
                "pass"
            )
        elif len(payslips) == 1:
            return self._create_check(
                "PAYG Income Verification",
                False,
                "Only one payslip provided. Further verification needed with tax return, assessment notice, ATO Income Statement, or PAYG Payment Summary.",
                0.8,
                "POLICY_PAYG_INCOME_VERIFICATION",
                None,
                "warning"
            )
        else:
            return self._create_check(
                "PAYG Income Verification",
                False,
                "No payslips provided.",
                0.8,
                "POLICY_PAYG_INCOME_VERIFICATION",
                None,
                "fail"
            )
    
    def _check_document_requirements(self, payslips: List[Dict[str, Any]], bank_statements: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Check Document requirements policy"""
        issues = []
        
        # Check payslip requirements
        for idx, payslip in enumerate(payslips):
            data = payslip.get('extracted_data', {})
            
            if not data.get('employee_name'):
                issues.append(f"Payslip #{idx+1} missing borrower's name")
            
            if not data.get('employer_name'):
                issues.append(f"Payslip #{idx+1} missing employer's name")
                
            if not data.get('abn'):
                issues.append(f"Payslip #{idx+1} missing employer ABN")
            
            # Check if payslip is not older than 60 days
            if data.get('pay_date'):
                try:
                    from dateutil import parser as date_parser
                    from datetime import datetime
                    
                    pay_date = date_parser.parse(data['pay_date'])
                    today = datetime.now()
                    days_old = (today - pay_date).days
                    
                    if days_old > 60:
                        issues.append(f"Payslip #{idx+1} is {days_old} days old, exceeding the 60-day limit")
                except:
                    issues.append(f"Payslip #{idx+1} has invalid pay date format")
        
        # Check bank statement requirements
        for idx, statement in enumerate(bank_statements):
            data = statement.get('extracted_data', {})
            
            if not any(transaction.get('description', '').lower() for transaction in data.get('transactions', [])):
                issues.append(f"Bank statement #{idx+1} missing salary credit descriptions")
        
        if issues:
            return self._create_check(
                "Document requirements",
                False,
                f"Document issues found: {'; '.join(issues)}",
                0.8,
                "POLICY_DOCUMENT_REQUIREMENTS",
                None,
                "fail"
            )
        
        return self._create_check(
            "Document requirements",
            True,
            "All document requirements met",
            0.8,
            "POLICY_DOCUMENT_REQUIREMENTS",
            None,
            "pass"
        )
    
    def _create_check(self, name: str, passed: bool, message: str, confidence: float,
                     policy_ref: str, exception_code: Optional[str] = None,
                     policy_section: Optional[str] = None) -> Dict[str, Any]:
        return {
            'name': name,
            'status': 'pass' if passed else ('warning' if confidence < 0.7 else 'fail'),
            'message': message,
            'confidence': confidence,
            'policy_reference': policy_ref,
            'exception_code': exception_code,
            'policy_section': policy_section or "General Validation"
        }
    
    def _check_date_freshness(self, date_str: str) -> Dict[str, Any]:
        try:
            if isinstance(date_str, str):
                doc_date = date_parser.parse(date_str)
            else:
                doc_date = date_str
            
            days_old = (datetime.now() - doc_date).days
            is_fresh = days_old <= self.CFG_FRESHNESS_DAYS
            
            return {
                'is_fresh': is_fresh,
                'days_old': days_old,
                'message': f"Document date: {doc_date.strftime('%Y-%m-%d')} ({days_old} days old)"
            }
        except Exception as e:
            return {
                'is_fresh': False,
                'days_old': 999,
                'message': f"Could not parse date: {date_str}"
            }
    
    def _extract_summary_data(self, payslips: List[Dict[str, Any]], 
                             bank_statements: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary = {
            'applicant_name': None,
            'employer': None,
            'monthly_income': None,
            'account_details': None
        }
        
        if payslips:
            latest = payslips[0].get('extracted_data', {})
            summary['applicant_name'] = latest.get('employee_name')
            summary['employer'] = latest.get('employer_name')
            summary['monthly_income'] = latest.get('net_pay')
        
        if bank_statements:
            latest = bank_statements[0].get('extracted_data', {})
            summary['account_details'] = {
                'holder': latest.get('account_holder'),
                'number': latest.get('account_number'),
                'balance': latest.get('closing_balance')
            }
        
        return summary
