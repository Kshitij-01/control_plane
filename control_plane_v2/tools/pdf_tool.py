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
        # ROBUST MULTI-LAYER PARSING: Pydantic → json-repair → demjson3 → Fallback
        
        # Extract JSON from code blocks if present
        if "```json" in result_text:
            json_start = result_text.find("```json") + 7
            json_end = result_text.find("```", json_start)
            result_text = result_text[json_start:json_end].strip()
        elif "```" in result_text:
            json_start = result_text.find("```") + 3
            json_end = result_text.find("```", json_start)
            result_text = result_text[json_start:json_end].strip()
        
        # Layer 1: Try strict standard JSON parsing (fastest)
        try:
            extracted_data = json.loads(result_text)
            logger.info(f"[PDF_TOOL] Successfully parsed JSON (strict parser) from {Path(pdf_path).name}")
            return extracted_data
        except json.JSONDecodeError as e:
            logger.warning(f"[PDF_TOOL] Strict JSON parsing failed: {e}")
        
        # Layer 2: Try Pydantic's lenient JSON parsing
        try:
            from pydantic import TypeAdapter
            # Pydantic can handle some malformed JSON
            adapter = TypeAdapter(dict)
            extracted_data = adapter.validate_json(result_text)
            logger.info(f"[PDF_TOOL] Successfully parsed JSON (Pydantic) from {Path(pdf_path).name}")
            return extracted_data
        except Exception as e:
            logger.warning(f"[PDF_TOOL] Pydantic JSON parsing failed: {e}")
        
        # Layer 3: Try json-repair (designed for LLM outputs)
        try:
            from json_repair import repair_json
            repaired_text = repair_json(result_text)
            extracted_data = json.loads(repaired_text)
            logger.info(f"[PDF_TOOL] Successfully parsed JSON (json-repair) from {Path(pdf_path).name}")
            return extracted_data
        except Exception as e:
            logger.warning(f"[PDF_TOOL] json-repair parsing failed: {e}")
        
        # Layer 4: Try demjson3 (most lenient)
        try:
            import demjson3
            extracted_data = demjson3.decode(result_text)
            logger.info(f"[PDF_TOOL] Successfully parsed JSON (demjson3) from {Path(pdf_path).name}")
            return extracted_data
        except Exception as e:
            logger.warning(f"[PDF_TOOL] demjson3 parsing failed: {e}")
        
        # All parsers failed - return error with truncated response
        logger.error(f"[PDF_TOOL] ALL JSON parsers failed for {Path(pdf_path).name}")
        logger.error(f"[PDF_TOOL] Response preview (first 500 chars): {result_text[:500]}")
        logger.error(f"[PDF_TOOL] Response preview (last 500 chars): {result_text[-500:]}")
        return {
            "error": "Failed to parse JSON with all parsers",
            "raw_response_preview": result_text[:1000] + "\n...\n" + result_text[-1000:],
            "parsers_tried": ["json.loads", "pydantic", "json-repair", "demjson3"]
        }
    
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
    
    async def _extract_single_pdf_safe(
        self,
        pdf_path: str,
        schema: Dict[str, Any],
        extraction_instructions: str,
        index: int,
        total: int
    ) -> Dict[str, Any]:
        """
        Extract from single PDF with error handling and timeout
        
        Args:
            pdf_path: Path to PDF file
            schema: JSON schema for extraction
            extraction_instructions: Additional instructions
            index: Current PDF index (1-based)
            total: Total number of PDFs
            
        Returns:
            Dict with extraction results or error
        """
        logger.info(f"[PDF_TOOL] Processing PDF {index}/{total}: {Path(pdf_path).name}")
        
        try:
            # Add 10-minute timeout per PDF (increased to handle complex multi-page reports)
            import asyncio
            async with asyncio.timeout(600):
                data = await self.extract_structured_data(
                    pdf_path=pdf_path,
                    schema=schema,
                    extraction_instructions=extraction_instructions
                )
            
            return {
                "pdf_path": pdf_path,
                "pdf_name": Path(pdf_path).name,
                "data": data,
                "success": True,
                "error": None
            }
            
        except asyncio.TimeoutError:
            logger.error(f"[PDF_TOOL] Timeout processing {Path(pdf_path).name} (>600s)")
            return {
                "pdf_path": pdf_path,
                "pdf_name": Path(pdf_path).name,
                "data": None,
                "success": False,
                "error": "Timeout: PDF processing exceeded 600 seconds"
            }
            
        except Exception as e:
            logger.error(f"[PDF_TOOL] Error processing {Path(pdf_path).name}: {e}")
            return {
                "pdf_path": pdf_path,
                "pdf_name": Path(pdf_path).name,
                "data": None,
                "success": False,
                "error": str(e)
            }
    
    async def extract_from_multiple_pdfs(
        self,
        pdf_paths: List[str],
        schema: Dict[str, Any],
        extraction_instructions: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Extract data from multiple PDFs in PARALLEL using asyncio.gather
        
        Args:
            pdf_paths: List of PDF file paths
            schema: JSON schema for extraction
            extraction_instructions: Additional instructions
            
        Returns:
            List of extracted data (one dict per PDF)
        """
        import asyncio
        from pathlib import Path
        
        logger.info(f"[PDF_TOOL] Starting PARALLEL extraction of {len(pdf_paths)} PDFs")
        
        # CRITICAL: PRE-VALIDATE ALL PATHS (Prevent hallucinated filenames from wasting API calls)
        valid_paths = []
        invalid_results = []
        
        for pdf_path in pdf_paths:
            if Path(pdf_path).exists():
                valid_paths.append(pdf_path)
            else:
                logger.error(f"[PDF_TOOL] INVALID PATH - File does not exist: {pdf_path}")
                invalid_results.append({
                    "pdf_path": pdf_path,
                    "pdf_name": Path(pdf_path).name,
                    "success": False,
                    "error": f"[Errno 2] No such file or directory: '{pdf_path}'",
                    "data": None
                })
        
        if invalid_results:
            logger.warning(f"[PDF_TOOL] Skipping {len(invalid_results)} non-existent files")
            logger.warning(f"[PDF_TOOL] Processing only {len(valid_paths)} valid paths")
        
        # Only process valid paths (avoid wasted API calls)
        if not valid_paths:
            logger.error(f"[PDF_TOOL] NO VALID PATHS - All {len(pdf_paths)} files are non-existent!")
            return invalid_results
        
        # Create tasks for parallel execution (ONLY for valid paths)
        tasks = [
            self._extract_single_pdf_safe(
                pdf_path=pdf_path,
                schema=schema,
                extraction_instructions=extraction_instructions,
                index=i+1,
                total=len(valid_paths)
            )
            for i, pdf_path in enumerate(valid_paths)
        ]
        
        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Combine valid results with invalid results
        all_results = results + invalid_results
        
        success_count = sum(1 for r in all_results if r.get("success"))
        logger.info(f"[PDF_TOOL] Completed PARALLEL extraction: {success_count}/{len(pdf_paths)} successful ({len(invalid_results)} skipped as non-existent)")
        
        return all_results


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

