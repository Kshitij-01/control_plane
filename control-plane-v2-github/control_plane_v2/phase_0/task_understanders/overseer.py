"""
Agent 1c: Overseer (Quality Control)

Reviews task classifications to ensure completeness:
- All prerequisites identified
- Side tasks have sufficient information
- Resources properly allocated
- No missing dependencies
"""

import json
import logging
from typing import Dict, List, Tuple

from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage

from ..messages import TaskClassificationProposal, TaskAnalysisRequest

logger = logging.getLogger(__name__)


class OverseerAgent:
    """
    Overseer Agent - Reviews classification quality
    
    Ensures that:
    - Side tasks have all necessary information (table names, file paths, etc.)
    - All prerequisites are covered
    - Resources and credentials are properly distributed
    - No critical information is missing
    """
    
    SYSTEM_PROMPT = """You are a quality control reviewer. Keep classifications SIMPLE.

YOUR JOB: Make sure side tasks are BASIC checks only.

IMPORTANT: If transformation_config.skip_side_tasks==true, APPROVE empty side_tasks list.

APPROVE if side tasks are simple:
✅ "Verify connection to DB at host:port and table 'X' exists (using provided credentials)"
✅ "Verify file exists at 'data/input.csv' (catalog will resolve path)"
✅ "Verify connection to server at host:port with provided credentials"

REJECT if side tasks are TOO detailed:
❌ "Verify read/write/create permissions" → TOO MUCH, not a basic check
❌ "Validate JSON structure has required fields" → TOO MUCH, that's core task work
❌ "Check schema compatibility" → TOO MUCH
❌ Uses placeholders like "{table}" or "from context" → FIX: use actual names

CRITICAL CHECKS (must reject if these fail):
1. Placeholders used? → CRITICAL issue
2. Missing connection targets (host, database, table names)? → CRITICAL issue
3. File references unclear? → Use relative paths (e.g., 'outputs/result.json') - catalog resolves absolute paths at runtime

NOTE: 
- Credentials (passwords) are in the manifest and automatically provided to agents. Task descriptions should NOT list passwords - just specify connection targets.
- File paths should be relative (e.g., 'data/input.csv', 'outputs/result.json') - the file catalog automatically resolves absolute paths during execution
- Agents will use the catalog to find files from previous tasks

DON'T BE PEDANTIC:
- Don't ask for permission checks (read/write/create permissions)
- Don't ask for schema validation (default schemas like 'public' are fine)
- Don't ask for JSON structure validation
- Don't ask for "what if file is corrupted" checks
- Don't require fully-qualified table names if database is specified in connection

DEFAULT ASSUMPTIONS ARE OK:
- PostgreSQL tables in 'public' schema by default
- MySQL tables in the connected database by default
- These are standard database behaviors

Side tasks = "Can we START?" not "Will everything work perfectly?"

YOUR RESPONSE FORMAT:
{
  "approved": true/false,
  "issues": [
    {
      "category": "side_task_info_gap" / "missing_prerequisite" / "resource_distribution",
      "severity": "critical" / "high" / "medium",
      "description": "Specific issue description",
      "task_id": "side_1" (if applicable),
      "suggestion": "How to fix it"
    }
  ],
  "feedback_to_analysts": "Detailed feedback on what needs to be improved",
  "confidence": 0.0-1.0
}

If there are CRITICAL or HIGH severity issues, set approved=false.
If only MEDIUM or no issues, set approved=true.

Be thorough but reasonable - don't be pedantic about minor details.
"""
    
    def __init__(self, model_client: ChatCompletionClient):
        self._model_client = model_client
        logger.info("OverseerAgent initialized")
    
    async def review_classification(
        self,
        request: TaskAnalysisRequest,
        classification: TaskClassificationProposal
    ) -> Tuple[bool, Dict]:
        """
        Review the classification for completeness
        
        Returns:
            (approved: bool, review_report: dict)
        """
        logger.info(f"Overseer reviewing classification for task: {request.task_id}")
        
        # Build review context
        review_context = self._build_review_context(request, classification)
        
        # Get overseer's review
        response = await self._model_client.create([
            SystemMessage(content=self.SYSTEM_PROMPT),
            UserMessage(content=review_context, source="user")
        ])
        
        # Parse review
        review_report = self._parse_review(str(response.content))
        
        approved = review_report.get("approved", False)
        num_issues = len(review_report.get("issues", []))
        
        if approved:
            logger.info(f"Overseer APPROVED classification ({num_issues} minor issues)")
        else:
            logger.warning(f"Overseer REJECTED classification ({num_issues} issues found)")
        
        return approved, review_report
    
    def _build_review_context(
        self,
        request: TaskAnalysisRequest,
        classification: TaskClassificationProposal
    ) -> str:
        """Build context for overseer review"""
        lines = []
        
        lines.append("TASK CLASSIFICATION REVIEW")
        lines.append("="*60)
        
        lines.append(f"\nTASK ID: {request.task_id}")
        lines.append(f"TASK DESCRIPTION: {request.task_description}")
        
        # Connections provided
        if request.connections:
            lines.append(f"\nCONNECTIONS PROVIDED:")
            for conn in request.connections:
                lines.append(f"- {conn.id} ({conn.type}): {conn.host or ''}/{conn.database or ''}")
        
        # Files provided (with manifest content)
        if request.files:
            lines.append(f"\nFILES PROVIDED:")
            for f in request.files:
                size_info = f" ({f.size_mb}MB)" if f.size_mb else ""
                lines.append(f"- {f.path}{size_info}")
                if f.description:
                    lines.append(f"  Purpose: {f.description}")
                
                # Include manifest content for Overseer to review
                if f.path and (f.path.endswith('.json') or 'manifest' in f.path.lower()):
                    try:
                        import os
                        if os.path.exists(f.path):
                            with open(f.path, 'r', encoding='utf-8') as file:
                                manifest_content = file.read()
                                lines.append(f"  MANIFEST CONTENT:")
                                lines.append(f"{manifest_content[:3000]}")  # First 3000 chars
                                if len(manifest_content) > 3000:
                                    lines.append("  ... (truncated)")
                    except Exception as e:
                        logger.debug(f"Could not read manifest {f.path}: {e}")
        
        # Additional context
        if request.additional_context:
            lines.append(f"\nADDITIONAL CONTEXT:")
            for key, value in request.additional_context.items():
                lines.append(f"- {key}: {str(value)[:300]}")  # First 300 chars per key
        
        # Proposed Classification
        lines.append(f"\nPROPOSED CLASSIFICATION:")
        lines.append(f"Agent: {classification.agent_id}")
        lines.append(f"Confidence: {classification.confidence}")
        
        lines.append(f"\nCORE TASKS ({len(classification.core_tasks)}):")
        for task in classification.core_tasks:
            lines.append(f"- {task.id}: {task.description}")
        
        lines.append(f"\nSIDE TASKS ({len(classification.side_tasks)}):")
        for task in classification.side_tasks:
            lines.append(f"- {task.id} ({task.priority}): {task.description}")
        
        lines.append("\n" + "="*60)
        lines.append("Review the classification above. Do side tasks have ALL necessary information?")
        lines.append("Check for: specific table names, clear file references (relative paths OK - catalog resolves them), resource identifiers.")
        lines.append("Provide your review in JSON format.")
        
        return "\n".join(lines)
    
    def _parse_review(self, response_text: str) -> Dict:
        """Parse overseer's review response"""
        import re
        
        # Try to extract JSON from response
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                logger.error("Could not find JSON in overseer response")
                return {
                    "approved": False,
                    "issues": [{
                        "category": "parsing_error",
                        "severity": "critical",
                        "description": "Could not parse overseer response",
                        "suggestion": "Retry review"
                    }],
                    "feedback_to_analysts": response_text,
                    "confidence": 0.0
                }
        
        try:
            review = json.loads(json_str)
            return review
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse overseer JSON: {e}")
            return {
                "approved": False,
                "issues": [{
                    "category": "parsing_error",
                    "severity": "critical",
                    "description": f"JSON parse error: {str(e)}",
                    "suggestion": "Retry review"
                }],
                "feedback_to_analysts": response_text,
                "confidence": 0.0
            }

