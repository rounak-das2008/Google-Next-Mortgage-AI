# Mortgage Processing Application

## AI-Powered Standard Income Document Verification System

A comprehensive mortgage processing web application featuring Google Cloud Document AI OCR, Gemini-powered document classification, and automated Standard Income (Pay-As-You-Go) income verification based on Australian banking regulations.

---

## 🎯 Key Features

### For Brokers
- **Multi-step Application Workflow** with visual progress tracking
- **Drag-and-drop Document Upload** (Bank Statements & Payslips)
- **Real-time AI Processing** with visual feedback
- **Comprehensive Validation Results** with confidence scores
- **AI-Generated Summaries** for quick application overview

### For Assessors
- **Centralized Dashboard** with all applications
- **Advanced Filtering** by status and search
- **Detailed Validation Review** with 30+ automated checks
- **Decision Management** (Approve/Reject/Request Info)
- **Document Viewer** with extracted data overlay

### Technical Capabilities
- ✅ **Automated Document Classification** (Bank Statement vs Payslip)
- ✅ **OCR Data Extraction** with GCP Document AI
- ✅ **30+ Standard Income Policy Validations** (Section 3.2 & 3.3)
- ✅ **Cross-Document Verification** (Name matching, amount reconciliation)
- ✅ **Exception Handling** with escalation codes
- ✅ **Confidence Scoring** for all extractions
- ✅ **Policy Reference Tracking** for audit compliance

---

## 🏗️ Architecture

**Stack:**
- **Backend:** Python 3.11 + Flask
- **Frontend:** Jinja2 Templates + Tailwind CSS
- **OCR:** Google Cloud Document AI
- **AI:** Gemini 2.5 Flash/Pro
- **Database:** Google Cloud Firestore (with in-memory fallback)
- **Storage:** Local filesystem (uploads/)

**Design Pattern:** Modular service-oriented architecture with clear separation of concerns

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Google Cloud SDK with ADC configured
- GCP Project with billing enabled
- Gemini API key

### 1. Install Dependencies

Already installed in Replit. For local setup:

```bash
pip install flask google-cloud-documentai google-cloud-firestore google-generativeai \
    PyPDF2 pdf2image Pillow python-dateutil pydantic python-dotenv werkzeug gunicorn
```

### 2. Configure Environment

Create `.env` file:

```env
SESSION_SECRET=your-secret-key
GEMINI_API_KEY=your-gemini-api-key
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us
GCP_PROCESSOR_ID=your-processor-id
```

### 3. Set up GCP ADC

```bash
gcloud auth application-default login
```

### 4. Run Application

```bash
python app.py
```

Access at: **http://localhost:5000**

---

## 📖 Complete Setup Guide

For detailed step-by-step instructions including:
- GCP project setup
- API enablement
- Document AI processor creation
- Firestore configuration
- Local replication guide
- Troubleshooting

**See:** [SETUP.md](SETUP.md)

---

## 🎨 UI Design

**Theme:** 
- **Primary Color:** ABC Orange (#FF6200)
- **Secondary:** ABC Blue (#002855)
- **Clean, modern banking aesthetic**
- **Responsive design** for desktop and mobile
- **Accessibility-focused** with clear visual indicators

---

## 📊 Validation Engine

### Document Requirements (Standard Income)

**Minimum Required:**
- 2 consecutive recent payslips
- 1-3 months bank statements

**Validation Categories:**

1. **Document Completeness** (3 checks)
2. **Payslip Validations** (7 checks per payslip)
3. **Bank Statement Validations** (5 checks per statement)
4. **Cross-Document Validations** (2 checks)
5. **Standard Income Policy Validations** (6 policy checks)

**Total: 30+ automated validation checks**

### Policy References

Based on:
- Section 3.2: Standard Income Income Definitions & Eligibility
- Section 3.3: Standard Income Income Verification Requirements

All checks include:
- ✅ Pass/Fail/Warning status
- 📊 Confidence scores (0-100%)
- 📚 Policy section references
- 🚩 Exception codes for escalation

---

## 🔐 Security & Compliance

- **Role-based Access Control** (Broker/Assessor separation)
- **Session Management** with secure secrets
- **Document Storage** with access controls
- **Audit Trail** in Firestore
- **Data Privacy** compliant design
- **GCP ADC** for secure authentication

---

## 🧪 Testing

### Sample Test Flow

1. **Login as Broker**
   - Username: `broker1`
   - Password: any (demo mode)

2. **Create Application**
   - Applicant: John Smith
   - Type: Individual
   - Role: Primary Applicant

3. **Upload Documents**
   - 2 payslips (PDF)
   - 1 bank statement (PDF)

4. **Review Results**
   - Check validation status
   - Review AI summary
   - Verify extracted data

5. **Submit Application**

6. **Login as Assessor**
   - Username: `assessor1`
   - Password: any

7. **Review & Decide**
   - View application
   - Review all checks
   - Make decision (Approve/Reject)

---

## 📁 Project Structure

```
├── app.py                      # Main Flask application
├── services/
│   ├── firestore_service.py    # Database operations
│   ├── document_processor.py   # OCR & extraction
│   ├── validation_engine.py    # Standard Income validation
│   └── gemini_service.py       # AI classification
├── templates/                   # HTML templates (8 files)
├── uploads/                     # Document storage
├── .env                        # Environment config
├── SETUP.md                    # Setup instructions
└── README.md                   # This file
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SESSION_SECRET` | Flask session secret | Yes |
| `GEMINI_API_KEY` | Gemini AI API key | Yes |
| `GCP_PROJECT_ID` | GCP project ID | Optional (ADC) |
| `GCP_LOCATION` | Document AI location | Optional |
| `GCP_PROCESSOR_ID` | Document AI processor | Optional |

### Validation Thresholds (Configurable)

```python
CFG_FRESHNESS_DAYS = 60        # Document age limit
MIN_TENURE_FULL_TIME = 6       # Months
MIN_TENURE_CASUAL = 12         # Months
MIN_INCOME_THRESHOLD = 4000    # AUD
```

---

## 🚀 Deployment

### Replit (Current)

Application auto-deploys with configured workflow.

### Production Deployment

**Recommended:** Google Cloud Run

```bash
# Build container
gcloud builds submit --tag gcr.io/PROJECT_ID/mortgage-app

# Deploy
gcloud run deploy mortgage-app \
    --image gcr.io/PROJECT_ID/mortgage-app \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated
```

**Alternative:** App Engine, Cloud Functions, VM, etc.

---

## 🐛 Troubleshooting

### Common Issues

**"Firestore not available"**
```bash
gcloud auth application-default login
```

**"Gemini API error"**
- Check API key in .env
- Verify quota limits

**"Document AI not available"**
- App uses fallback text extraction
- Optional: Create processor in GCP

**See:** [SETUP.md](SETUP.md) for detailed troubleshooting

---

## 📈 Future Enhancements

- [ ] Additional document types (Tax returns, Employment contracts)
- [ ] Real-time collaboration between broker and assessor
- [ ] Bulk document processing
- [ ] Advanced analytics dashboard
- [ ] Email notifications
- [ ] Document comparison tools
- [ ] ML model retraining pipeline
- [ ] Multi-language support

---

## 📄 License

Demo application for mortgage processing. Adapt for your organization's compliance requirements.

---

## 🤝 Support

For setup assistance, see [SETUP.md](SETUP.md) or contact your GCP administrator.

---

**Version:** 1.0.0  
**Created:** October 2025  
**Powered by:** Google Cloud Platform + Gemini AI
