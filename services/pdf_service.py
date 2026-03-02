"""
PDF Generation Service for Application Review Summary
Generates professional, structured PDF reports for mortgage applications.
"""

import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, 
    PageBreak, HRFlowable, Image
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfgen import canvas


class PDFService:
    """Service for generating professional PDF reports."""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        
        # Brand colors
        self.primary_color = colors.HexColor('#0F5FDC')  # HCLTech Primary
        self.secondary_color = colors.HexColor('#4A4A4A')  # Dark gray
        self.success_color = colors.HexColor('#22C55E')  # Green
        self.danger_color = colors.HexColor('#EF4444')  # Red
        self.warning_color = colors.HexColor('#F59E0B')  # Yellow
        self.info_color = colors.HexColor('#3B82F6')  # Blue
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the PDF."""
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=20,
            textColor=colors.HexColor('#FF6200'),
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        # Section header style
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceBefore=20,
            spaceAfter=10,
            textColor=colors.HexColor('#FF6200'),
            borderPadding=5,
            fontName='Helvetica-Bold'
        ))
        
        # Subsection header style
        self.styles.add(ParagraphStyle(
            name='SubsectionHeader',
            parent=self.styles['Heading3'],
            fontSize=12,
            spaceBefore=15,
            spaceAfter=8,
            textColor=colors.HexColor('#4A4A4A'),
            fontName='Helvetica-Bold'
        ))
        
        # Body text style
        self.styles.add(ParagraphStyle(
            name='CustomBodyText',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=8,
            leading=14,
            alignment=TA_JUSTIFY
        ))
        
        # Info box style
        self.styles.add(ParagraphStyle(
            name='InfoBox',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=5,
            leading=14,
            textColor=colors.HexColor('#4A4A4A')
        ))
        
        # Small text style
        self.styles.add(ParagraphStyle(
            name='SmallText',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.gray,
            alignment=TA_CENTER
        ))

    def generate_application_pdf(self, application: dict) -> bytes:
        """Generate a complete PDF review summary for an application."""
        buffer = io.BytesIO()
        
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=20*mm,
            leftMargin=20*mm,
            topMargin=25*mm,
            bottomMargin=20*mm
        )
        
        # Build the document content
        content = []
        
        # Header Section
        content.extend(self._build_header(application))
        
        # Application Overview Section
        content.extend(self._build_overview_section(application))
        
        # AI Summary Section
        if application.get('ai_summary'):
            content.extend(self._build_ai_summary_section(application))
        
        # Validation Results Overview
        if application.get('validation_results'):
            content.extend(self._build_validation_overview_section(application))
        
        # Payslip Validation Checks
        validation_results = application.get('validation_results', {})
        if validation_results.get('payslip_checks'):
            content.extend(self._build_validation_checks_section(
                'Payslip Validation Checks', 
                validation_results['payslip_checks'],
                'payslip'
            ))
        
        # Bank Statement Validation Checks
        if validation_results.get('bank_statement_checks'):
            content.extend(self._build_validation_checks_section(
                'Bank Statement Validation Checks',
                validation_results['bank_statement_checks'],
                'bank'
            ))
        
        # Cross Validation Checks
        if validation_results.get('cross_validation_checks'):
            content.extend(self._build_validation_checks_section(
                'Cross Validation Checks',
                validation_results['cross_validation_checks'],
                'cross'
            ))
        
        # Standard Income Policy Checks
        if validation_results.get('standard_income_policy_checks'):
            content.extend(self._build_standard_income_policy_section(validation_results['standard_income_policy_checks']))
        
        # Extracted Document Data
        if application.get('processed_documents'):
            content.extend(self._build_extracted_data_section(application))
        
        # Footer
        content.extend(self._build_footer(application))
        
        # Build the PDF
        doc.build(content, onFirstPage=self._add_page_number, onLaterPages=self._add_page_number)
        
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        return pdf_bytes
    
    def _add_page_number(self, canvas, doc):
        """Add page numbers to each page."""
        page_num = canvas.getPageNumber()
        text = f"Page {page_num}"
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.gray)
        canvas.drawCentredString(A4[0]/2, 10*mm, text)
        canvas.restoreState()
    
    def _build_header(self, application: dict) -> list:
        """Build the header section of the PDF."""
        content = []
        
        # Title
        content.append(Paragraph("Mortgage Application Review Report", self.styles['CustomTitle']))
        content.append(Spacer(1, 5*mm))
        
        # Subtitle with generation date
        generated_at = datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')
        content.append(Paragraph(
            f"Generated on {generated_at}",
            self.styles['SmallText']
        ))
        
        content.append(Spacer(1, 3*mm))
        
        # Separator line
        content.append(HRFlowable(
            width="100%",
            thickness=2,
            color=self.primary_color,
            spaceBefore=5,
            spaceAfter=10
        ))
        
        return content
    
    def _build_overview_section(self, application: dict) -> list:
        """Build the application overview section."""
        content = []
        
        content.append(Paragraph("Application Overview", self.styles['SectionHeader']))
        
        # Application details table
        app_id = application.get('application_id', 'N/A')
        if len(app_id) > 20:
            app_id = app_id[:20] + '...'
        
        status = application.get('status', 'N/A').replace('_', ' ').title()
        created_at = application.get('created_at', 'N/A')
        if created_at and len(created_at) > 10:
            created_at = created_at[:10]
        
        data = [
            ['Application ID:', app_id, 'Status:', status],
            ['Applicant Name:', application.get('applicant_name', 'N/A'), 
             'Applicant Type:', application.get('applicant_type', 'N/A')],
            ['Applicant Role:', application.get('applicant_role', 'N/A'),
             'Created Date:', created_at],
        ]
        
        table = Table(data, colWidths=[80, 150, 80, 150])
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), self.secondary_color),
            ('TEXTCOLOR', (2, 0), (2, -1), self.secondary_color),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        content.append(table)
        content.append(Spacer(1, 5*mm))
        
        return content
    
    def _build_ai_summary_section(self, application: dict) -> list:
        """Build the AI-generated summary section."""
        content = []
        
        content.append(Paragraph("AI-Generated Summary", self.styles['SectionHeader']))
        
        # Info box with AI summary
        summary_text = application.get('ai_summary', 'No summary available.')
        
        # Create a styled box for the summary
        summary_data = [[Paragraph(summary_text, self.styles['CustomBodyText'])]]
        summary_table = Table(summary_data, colWidths=[450])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EFF6FF')),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#BFDBFE')),
        ]))
        
        content.append(summary_table)
        content.append(Spacer(1, 5*mm))
        
        return content
    
    def _build_validation_overview_section(self, application: dict) -> list:
        """Build the validation results overview section."""
        content = []
        
        content.append(Paragraph("Validation Results Summary", self.styles['SectionHeader']))
        
        validation = application.get('validation_results', {})
        summary = validation.get('summary', {})
        
        total = summary.get('total_checks', 0)
        passed = summary.get('passed', 0)
        failed = summary.get('failed', 0)
        warnings = summary.get('warnings', 0)
        
        # Summary statistics table
        data = [
            ['Total Checks', 'Passed ✓', 'Failed ✗', 'Warnings ⚠'],
            [str(total), str(passed), str(failed), str(warnings)]
        ]
        
        table = Table(data, colWidths=[110, 110, 110, 110])
        table.setStyle(TableStyle([
            # Header row
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F3F4F6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.secondary_color),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Value row styling
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, 1), 18),
            ('BACKGROUND', (0, 1), (0, 1), colors.HexColor('#DBEAFE')),  # Blue
            ('BACKGROUND', (1, 1), (1, 1), colors.HexColor('#DCFCE7')),  # Green
            ('BACKGROUND', (2, 1), (2, 1), colors.HexColor('#FEE2E2')),  # Red
            ('BACKGROUND', (3, 1), (3, 1), colors.HexColor('#FEF3C7')),  # Yellow
            ('TEXTCOLOR', (0, 1), (0, 1), self.info_color),
            ('TEXTCOLOR', (1, 1), (1, 1), self.success_color),
            ('TEXTCOLOR', (2, 1), (2, 1), self.danger_color),
            ('TEXTCOLOR', (3, 1), (3, 1), self.warning_color),
            
            # Padding and borders
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ]))
        
        content.append(table)
        content.append(Spacer(1, 5*mm))
        
        return content
    
    def _build_validation_checks_section(self, title: str, checks: list, check_type: str) -> list:
        """Build a validation checks section with passed and failed checks."""
        content = []
        
        content.append(Paragraph(title, self.styles['SectionHeader']))
        
        if not checks:
            content.append(Paragraph("No validation checks available.", self.styles['CustomBodyText']))
            return content
        
        # Separate passed and failed checks
        passed_checks = [c for c in checks if c.get('status') != 'fail']
        failed_checks = [c for c in checks if c.get('status') == 'fail']
        
        # Build table for passed checks
        if passed_checks:
            content.append(Paragraph("Passed & Warning Checks", self.styles['SubsectionHeader']))
            content.extend(self._build_checks_table(passed_checks))
        
        # Build table for failed checks
        if failed_checks:
            content.append(Paragraph("Failed Checks", self.styles['SubsectionHeader']))
            content.extend(self._build_checks_table(failed_checks, is_failed=True))
        
        return content
    
    def _build_checks_table(self, checks: list, is_failed: bool = False) -> list:
        """Build a table for validation checks."""
        content = []
        
        # Table header
        header = ['Status', 'Validation Check', 'Details', 'Confidence']
        data = [header]
        
        for check in checks:
            status = check.get('status', 'N/A')
            status_symbol = '✓' if status == 'pass' else ('✗' if status == 'fail' else '⚠')
            
            name = check.get('name', 'N/A')
            if len(name) > 30:
                name = name[:30] + '...'
            
            message = check.get('message', 'N/A')
            if len(message) > 50:
                message = message[:50] + '...'
            
            confidence = check.get('confidence', 0)
            conf_str = f"{int(confidence * 100)}%"
            
            data.append([status_symbol, name, message, conf_str])
        
        col_widths = [40, 120, 200, 60]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        
        # Base style
        style_commands = [
            # Header
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F3F4F6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.secondary_color),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Body
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (3, 1), (3, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Padding and borders
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ]
        
        # Add row backgrounds based on status
        for i, check in enumerate(checks, 1):
            status = check.get('status', '')
            if status == 'pass':
                style_commands.append(('TEXTCOLOR', (0, i), (0, i), self.success_color))
            elif status == 'fail':
                style_commands.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FEF2F2')))
                style_commands.append(('TEXTCOLOR', (0, i), (0, i), self.danger_color))
            elif status == 'warning':
                style_commands.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FFFBEB')))
                style_commands.append(('TEXTCOLOR', (0, i), (0, i), self.warning_color))
        
        table.setStyle(TableStyle(style_commands))
        content.append(table)
        content.append(Spacer(1, 3*mm))
        
        return content
    
    def _build_standard_income_policy_section(self, standard_income_policy_checks: dict) -> list:
        """Build the Standard Income Policy Checks section."""
        content = []
        
        content.append(Paragraph("Standard Income Policy Checks", self.styles['SectionHeader']))
        
        checks = standard_income_policy_checks.get('checks', [])
        if not checks:
            content.append(Paragraph("No Standard Income policy checks available.", self.styles['CustomBodyText']))
            return content
        
        # Separate passed and failed checks
        passed_checks = [c for c in checks if c.get('status') != 'fail']
        failed_checks = [c for c in checks if c.get('status') == 'fail']
        
        # Build passed checks table
        if passed_checks:
            content.append(Paragraph("Passed Checks", self.styles['SubsectionHeader']))
            content.extend(self._build_standard_income_checks_table(passed_checks))
        
        # Build failed checks table
        if failed_checks:
            content.append(Paragraph("Failed Checks", self.styles['SubsectionHeader']))
            content.extend(self._build_standard_income_checks_table(failed_checks, is_failed=True))
        
        # AI note
        note_data = [[Paragraph(
            "<b>Note:</b> These checks use Vertex AI (Gemini) to extract and summarize "
            "relevant income data from payslips using intelligent keyword matching and field analysis.",
            self.styles['InfoBox']
        )]]
        note_table = Table(note_data, colWidths=[450])
        note_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EFF6FF')),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#93C5FD')),
        ]))
        content.append(Spacer(1, 3*mm))
        content.append(note_table)
        content.append(Spacer(1, 5*mm))
        
        return content
    
    def _build_standard_income_checks_table(self, checks: list, is_failed: bool = False) -> list:
        """Build a table for Standard Income policy checks."""
        content = []
        
        header = ['Status', 'Policy Name', 'Summary']
        data = [header]
        
        for check in checks:
            status = check.get('status', 'N/A')
            status_symbol = '✓' if status == 'pass' else ('✗' if status == 'fail' else ('⚠' if status == 'warning' else '—'))
            
            name = check.get('name', 'N/A')
            if len(name) > 35:
                name = name[:35] + '...'
            
            message = check.get('message', 'N/A')
            # Remove detailed info marker if present
            if '**Additional Details:**' in message:
                message = message.split('**Additional Details:**')[0].strip()
            if len(message) > 80:
                message = message[:80] + '...'
            
            data.append([status_symbol, name, message])
        
        col_widths = [40, 150, 260]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        
        style_commands = [
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F3F4F6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), self.secondary_color),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ]
        
        for i, check in enumerate(checks, 1):
            status = check.get('status', '')
            if status == 'pass':
                style_commands.append(('TEXTCOLOR', (0, i), (0, i), self.success_color))
            elif status == 'fail':
                style_commands.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FEF2F2')))
                style_commands.append(('TEXTCOLOR', (0, i), (0, i), self.danger_color))
            elif status == 'warning':
                style_commands.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FFFBEB')))
                style_commands.append(('TEXTCOLOR', (0, i), (0, i), self.warning_color))
            elif status == 'not_applicable':
                style_commands.append(('TEXTCOLOR', (0, i), (0, i), colors.gray))
        
        table.setStyle(TableStyle(style_commands))
        content.append(table)
        content.append(Spacer(1, 3*mm))
        
        return content
    
    def _build_extracted_data_section(self, application: dict) -> list:
        """Build the extracted document data section."""
        content = []
        
        content.append(Paragraph("Extracted Document Data", self.styles['SectionHeader']))
        
        processed_docs = application.get('processed_documents', [])
        
        for doc in processed_docs:
            filename = doc.get('filename', 'Unknown Document')
            doc_type = doc.get('document_type', 'unknown').replace('_', ' ').title()
            
            content.append(Paragraph(f"<b>{filename}</b> ({doc_type})", self.styles['SubsectionHeader']))
            
            extracted_data = doc.get('extracted_data', {})
            
            # Filter out raw data fields
            exclude_keys = ['raw_text', 'raw_fields', 'text', 'confidence', 'document_type', 'salary_deposits']
            filtered_data = {k: v for k, v in extracted_data.items() if k not in exclude_keys and v}
            
            if filtered_data:
                # Build data table
                data = []
                for key, value in filtered_data.items():
                    formatted_key = key.replace('_', ' ').title()
                    value_str = str(value)
                    if len(value_str) > 60:
                        value_str = value_str[:60] + '...'
                    data.append([formatted_key, value_str])
                
                if data:
                    table = Table(data, colWidths=[150, 300])
                    table.setStyle(TableStyle([
                        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('TEXTCOLOR', (0, 0), (0, -1), self.secondary_color),
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
                        ('TOPPADDING', (0, 0), (-1, -1), 5),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ]))
                    content.append(table)
            
            # Add salary deposits if present
            salary_deposits = extracted_data.get('salary_deposits', [])
            if salary_deposits:
                content.append(Spacer(1, 2*mm))
                content.append(Paragraph("<b>Identified Salary Deposits:</b>", self.styles['InfoBox']))
                
                for deposit in salary_deposits[:5]:  # Limit to 5 deposits
                    amount = deposit.get('amount', 'N/A')
                    desc = deposit.get('description', 'N/A')[:50]
                    content.append(Paragraph(f"  • ${amount} - {desc}", self.styles['InfoBox']))
            
            content.append(Spacer(1, 3*mm))
        
        return content
    
    def _build_footer(self, application: dict) -> list:
        """Build the footer section."""
        content = []
        
        content.append(Spacer(1, 10*mm))
        
        # Separator line
        content.append(HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor('#E5E7EB'),
            spaceBefore=5,
            spaceAfter=10
        ))
        
        # Footer text
        content.append(Paragraph(
            "This document is auto-generated by the Mortgage Processing System. "
            "For any queries, please contact your loan officer.",
            self.styles['SmallText']
        ))
        
        content.append(Paragraph(
            f"Application ID: {application.get('application_id', 'N/A')}",
            self.styles['SmallText']
        ))
        
        return content
