"""
PDF Processing Tool for Worker Agent

Allows Worker to send PDFs directly to Claude Sonnet 4.5 for extraction.
"""

import logging
from pathlib import Path
from typing import Dict, Any, List
from control_plane_v2.bedrock_client import PDFDocument

logger = logging.getLogger(__name__)


class PDFExtractionTool:
    """
    Tool for extracting structured data from PDFs using Claude Sonnet 4.5
    
    Usage in Worker Agent:
        pdf_tool = PDFExtractionTool(bedrock_client)
        result = await pdf_tool.extract_structured_data(
            pdf_path="report.pdf",
            schema={"well_name": "str", "activities": "list", ...}
        )
    """
    
    def __init__(self, bedrock_client):
        """
        Args:
            bedrock_client: BedrockClaudeClient instance
        """
        self.client = bedrock_client
    
    async def extract_structured_data(
        self,
        pdf_path: str,
        schema: Dict[str, Any],
        extraction_instructions: str = ""
    ) -> Dict[str, Any]:
        """
        Extract structured data from PDF using Claude's native PDF support
        
        Args:
            pdf_path: Path to PDF file
            schema: JSON schema defining expected output structure
            extraction_instructions: Additional instructions for extraction
            
        Returns:
            Extracted data matching the schema
        """
        logger.info(f"[PDF_TOOL] Extracting data from {Path(pdf_path).name}")
        
        # Create PDF document
        pdf_doc = PDFDocument(pdf_path)
        logger.info(f"[PDF_TOOL] PDF size: {pdf_doc.file_size_mb:.2f}MB")
        
        # Build extraction prompt
        prompt = self._build_extraction_prompt(schema, extraction_instructions)
        
        # Create message with PDF + text
        # CRITICAL: We need to bypass AutoGen's UserMessage Pydantic validation
        # because it doesn't support multimodal content with PDF documents.
        # Instead, we create a custom message object that BedrockClaudeClient will accept.
        from autogen_core.models import UserMessage
        
        # Create a UserMessage object bypassing validation
        # Use object.__setattr__ to set content directly
        user_message = object.__new__(UserMessage)
        object.__setattr__(user_message, 'content', [
            pdf_doc.to_bedrock_content(),  # PDF document
            {"type": "text", "text": prompt}  # Extraction instructions
        ])
        object.__setattr__(user_message, 'source', 'user')
        object.__setattr__(user_message, 'models_usage', None)
        
        # Call Claude
        response = await self.client.create(
            messages=[user_message],
            json_output=True
        )
        
        # Parse response
        import json
        result_text = response.content
        
        # Handle different response formats (text, list of blocks, etc.)
        if isinstance(result_text, list):
            # Extract text from content blocks (skip thinking blocks if present)
            text_parts = []
            for block in result_text:
                if isinstance(block, dict):
                    # Check block type
                    if block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    # Skip thinking blocks (Claude 4.5 extended thinking)
                    elif block.get('type') == 'thinking':
                        continue
                else:
                    # String block
                    text_parts.append(str(block))
            
            result_text = '\n'.join(text_parts) if text_parts else "{}"
        else:
            result_text = str(result_text) if result_text else "{}"
        
        # Try to extract JSON from response
        try:
            # Look for JSON in code blocks
            if "```json" in result_text:
                json_start = result_text.find("```json") + 7
                json_end = result_text.find("```", json_start)
                result_text = result_text[json_start:json_end].strip()
            elif "```" in result_text:
                json_start = result_text.find("```") + 3
                json_end = result_text.find("```", json_start)
                result_text = result_text[json_start:json_end].strip()
            
            extracted_data = json.loads(result_text)
            logger.info(f"[PDF_TOOL] Successfully extracted data from {Path(pdf_path).name}")
            return extracted_data
            
        except json.JSONDecodeError as e:
            logger.error(f"[PDF_TOOL] Failed to parse JSON from Claude response: {e}")
            logger.error(f"[PDF_TOOL] Raw response: {result_text[:500]}...")
            return {"error": "Failed to parse JSON", "raw_response": result_text}
    
    def _build_extraction_prompt(self, schema: Dict[str, Any], custom_instructions: str) -> str:
        """Build extraction prompt from schema"""
        
        prompt_parts = []
        
        if custom_instructions:
            prompt_parts.append(custom_instructions)
            prompt_parts.append("\n")
        
        prompt_parts.append("Extract the following data from this PDF document:\n\n")
        prompt_parts.append("**Required JSON Schema:**\n```json\n")
        
        import json
        prompt_parts.append(json.dumps(schema, indent=2))
        prompt_parts.append("\n```\n\n")
        
        prompt_parts.append("**Instructions:**\n")
        prompt_parts.append("1. Extract ALL data matching the schema above\n")
        prompt_parts.append("2. Preserve exact values (numbers, dates, text) as they appear\n")
        prompt_parts.append("3. For tables, extract ALL rows (do not skip any)\n")
        prompt_parts.append("4. Return ONLY valid JSON matching the schema\n")
        prompt_parts.append("5. If a field is missing from the PDF, use `null`\n")
        prompt_parts.append("6. For multilingual content, preserve original language AND provide English translation\n\n")
        
        prompt_parts.append("Return the extracted data as a JSON object enclosed in ```json code blocks.")
        
        return "".join(prompt_parts)
    
    async def extract_from_multiple_pdfs(
        self,
        pdf_paths: List[str],
        schema: Dict[str, Any],
        extraction_instructions: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Extract data from multiple PDFs (processes sequentially)
        
        Args:
            pdf_paths: List of PDF file paths
            schema: JSON schema for extraction
            extraction_instructions: Additional instructions
            
        Returns:
            List of extracted data (one dict per PDF)
        """
        results = []
        
        for i, pdf_path in enumerate(pdf_paths, 1):
            logger.info(f"[PDF_TOOL] Processing PDF {i}/{len(pdf_paths)}: {Path(pdf_path).name}")
            
            try:
                data = await self.extract_structured_data(
                    pdf_path=pdf_path,
                    schema=schema,
                    extraction_instructions=extraction_instructions
                )
                results.append({
                    "pdf_path": pdf_path,
                    "pdf_name": Path(pdf_path).name,
                    "data": data,
                    "success": "error" not in data
                })
            except Exception as e:
                logger.error(f"[PDF_TOOL] Error processing {Path(pdf_path).name}: {e}")
                results.append({
                    "pdf_path": pdf_path,
                    "pdf_name": Path(pdf_path).name,
                    "data": None,
                    "success": False,
                    "error": str(e)
                })
        
        logger.info(f"[PDF_TOOL] Completed {len(results)} PDFs. Success: {sum(1 for r in results if r['success'])}/{len(results)}")
        return results


# Example usage
"""
from control_plane_v2.tools.pdf_tool import PDFExtractionTool

# In Worker Agent
pdf_tool = PDFExtractionTool(self.bedrock_client)

# Extract from single PDF
result = await pdf_tool.extract_structured_data(
    pdf_path="runs/phase2/extract/halliburton_ddr/Pemex/01_FEBRERO.pdf",
    schema={
        "metadata": {
            "date": "str",
            "operator": "str",
            "well": "str",
            "rig": "str"
        },
        "hourly_activities": [
            {
                "hour": "int",
                "activity_original": "str",
                "activity_english": "str",
                "duration_hours": "float"
            }
        ],
        "cost_data": {
            "daily_cost": "float",
            "cumulative_cost": "float",
            "afe_budget": "float"
        }
    },
    extraction_instructions="This is a 24-hour drilling report. Extract ALL hourly activities (24 rows). Translate Spanish to English."
)

# Extract from multiple PDFs
results = await pdf_tool.extract_from_multiple_pdfs(
    pdf_paths=[
        "pdf1.pdf",
        "pdf2.pdf",
        "pdf3.pdf"
    ],
    schema={...},
    extraction_instructions="..."
)
"""

