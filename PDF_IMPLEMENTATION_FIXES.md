# 🔧 PDF IMPLEMENTATION FIXES

**Based on:** DEEP_AUDIT_PDF_IMPLEMENTATION.md  
**Priority:** Critical response parsing fix

---

## 🔴 FIX #1: Improve Response Content Parsing (CRITICAL)

### **Issue:**
Current code assumes `response.content` is either a string or a list where the first element is text. This fails when:
- Extended thinking is enabled (thinking blocks appear first)
- Multiple content blocks exist
- Content blocks have different types

### **Location:**
`control_plane_v2/tools/pdf_tool.py` lines 77-81

### **Current Code:**
```python
result_text = response.content
if isinstance(result_text, list):
    result_text = result_text[0] if result_text else "{}"
```

### **Fixed Code:**
```python
result_text = response.content

# Handle different response formats
if isinstance(result_text, list):
    # Extract text from content blocks (skip thinking blocks)
    text_parts = []
    for block in result_text:
        if isinstance(block, dict):
            # Check block type
            if block.get('type') == 'text':
                text_parts.append(block.get('text', ''))
            # Skip thinking blocks
            elif block.get('type') == 'thinking':
                continue
        else:
            # String block
            text_parts.append(str(block))
    
    result_text = '\n'.join(text_parts) if text_parts else "{}"
else:
    result_text = str(result_text) if result_text else "{}"
```

### **Status:** ✅ Applied below

---

## 🟡 FIX #2: Add Page Count Validation (OPTIONAL)

### **Location:**
`control_plane_v2/bedrock_client.py` - PDFDocument class

### **Enhancement:**
```python
import fitz  # PyMuPDF

class PDFDocument:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        
        # Read PDF
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
            self.pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        # Validate file size
        self.file_size_mb = len(pdf_bytes) / (1024 * 1024)
        if self.file_size_mb > 32:
            raise ValueError(f"PDF file too large: {self.file_size_mb:.1f}MB (max 32MB)")
        
        # Validate page count (NEW)
        try:
            doc = fitz.open(pdf_path)
            self.page_count = len(doc)
            
            if self.page_count > 100:
                doc.close()
                raise ValueError(f"PDF has {self.page_count} pages (max 100 pages supported)")
            
            # Check for encryption
            if doc.is_encrypted:
                doc.close()
                raise ValueError(f"PDF is encrypted or password-protected (not supported)")
            
            doc.close()
        except Exception as e:
            if "PDF" in str(e):
                raise
            # If PyMuPDF fails, continue anyway (base64 validation will catch it)
```

### **Status:** ⏸️ Optional - Not critical for initial testing

---

## 🟢 FIX #3: Verify Pricing

### **Action Required:**
Check AWS Bedrock pricing page for Claude Sonnet 4.5 actual costs.

### **Current Estimate:**
- Input: $3.00 / 1M tokens
- Output: $15.00 / 1M tokens
- **Per run (26 PDFs): ~$1.95**

### **To Verify:**
1. Go to: https://aws.amazon.com/bedrock/pricing/
2. Find Claude Sonnet 4.5 pricing
3. Update documentation if different

### **Status:** ⏸️ Low priority - Estimate is reasonable

---

## ✅ FIXES APPLIED

See updated `control_plane_v2/tools/pdf_tool.py` below.

