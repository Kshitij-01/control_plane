"""
Agent 1a: Claude 4.5 Task Understander

Focuses on technical analysis:
- Implementation details
- Resource requirements
- Technical prerequisites
- Schema understanding
"""

import json
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

from autogen_core import RoutedAgent, MessageContext, message_handler, default_subscription, FunctionCall, CancellationToken
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, LLMMessage, FunctionExecutionResult
from autogen_core.tools import FunctionTool

from ..messages import (
    TaskAnalysisRequest,
    TaskClassificationProposal,
    CoreTask,
    SideTask
)

logger = logging.getLogger(__name__)


@default_subscription
class ClaudeTaskUnderstander(RoutedAgent):
    """
    Claude 4.5 Task Understander - Technical Analysis
    
    Analyzes tasks from a technical perspective:
    - What resources are needed?
    - What are the technical prerequisites?
    - How complex is the implementation?
    - What are the technical risks?
    """
    
    SYSTEM_PROMPT = """You are a simple task classifier.

YOUR JOB: Split tasks into CORE (the actual work) and SIDE (basic system checks).

SIDE TASKS = SYSTEM-LEVEL CHECKS ONLY:
- Can we connect to server X?
- Does table Y exist?
- Does file Z exist?
- Is library W installed?

That's it. Nothing more. NO DATA VALIDATION!

ABSOLUTELY FORBIDDEN IN SIDE TASKS:
- Checking specific columns exist
- Validating schemas
- Checking permissions (read/write/create)
- Validating JSON structure
- Checking data compatibility
- Any analysis of data content

Side tasks = "Can we reach the resource?" NOT "Is the resource correct?"

DON'T overthink it. Just basic existence checks.

CORE TASKS = THE ACTUAL WORK:
- Migrate data
- Transform files
- Train model
- Deploy service
- Whatever the user asked for

RULES:
1. **CHECK transformation_config.skip_side_tasks FIRST** - If true, provide EMPTY side_tasks array []
2. Use actual names from manifest (not placeholders like {table} or "from context")
3. Specify connection targets (host, database, table names) in side task descriptions  
4. Keep side tasks to 2-4 maximum
5. Keep descriptions SHORT (1 sentence each)

NOTE: Credentials are in the manifest and automatically provided to agents. Reference "using provided credentials" not passwords.

GOOD SIDE TASKS (System checks only):
- "Verify connection to database at host:port/db (using provided credentials) and table X exists"
- "Verify file exists at absolute/path/to/file"
- "Verify library X is installed"

SKIP_SIDE_TASKS HANDLING:
- If transformation_config.skip_side_tasks == true: Return "side_tasks": []
- Reasoning should explain that side tasks are skipped per configuration
- execution_order should only include core tasks

BAD SIDE TASKS (Data validation - FORBIDDEN!):
- "Verify table has columns A, B, C"
- "Verify file has valid JSON/CSV structure"
- "Check schema compatibility"
- "Verify read/write permissions"
- "Check data types match"

Rule: If it requires opening/reading/analyzing the resource, it's NOT a side task!

IMPORTANT RULES:
- Keep to 2-4 side tasks maximum - be VERY minimal!
- Combine related checks: "Connect to DB AND verify table exists" = 1 task
- Side tasks should NOT need detailed analysis of core work data (e.g., mapping plans)
- Focus on: "Do we have what we need to START?" not "Is everything perfect?"
- AVOID creating too many tasks - quality over quantity
- Each side task should be quick (30 seconds to 2 minutes)

OUTPUT FORMAT:
Provide your analysis as a structured JSON response with:
{
  "core_tasks": [
    {
      "id": "core_1",
      "description": "Detailed description",
      "subtasks": ["Step 1", "Step 2", ...],
      "estimated_duration": "2-4 hours",
      "can_be_divided": true/false,
      "division_strategy": "How to divide if applicable",
      "resource_requirements": {"compute": "...", "memory": "...", ...},
      "dependencies": ["side_1", "side_2"]
    }
  ],
  "side_tasks": [
    {
      "id": "side_1",
      "description": "What needs to be verified",
      "priority": "critical/high/medium/low",
      "blocking": true/false,
      "estimated_duration": "30 seconds",
      "verification_needed": true/false,
      "dependencies": []
    }
  ],
  "execution_order": ["side_1", "side_2", "core_1"],
  "reasoning": "Your detailed technical analysis and reasoning",
  "confidence": 0.85,
  "concerns": ["Any technical concerns or risks"]
}

Be thorough and identify ALL prerequisites. Missing a prerequisite causes failures later.
"""
    
    def __init__(self, model_client: ChatCompletionClient):
        super().__init__(description="Claude Task Understander - Technical Analysis")
        self._model_client = model_client
        
        # Create file reading tool
        self._read_file_tool = FunctionTool(
            self._read_file_impl,
            description="Read and parse a file (JSON, text, etc.) to extract information"
        )
        
        logger.info("ClaudeTaskUnderstander initialized with file reading capability")
    
    def _read_file_impl(self, file_path: str) -> str:
        """
        Tool implementation: Read and return file contents
        
        Args:
            file_path: Path to the file to read
            
        Returns:
            File contents as string
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return f"Error: File not found: {file_path}"
            
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # If JSON, parse and return formatted
            if file_path.endswith('.json'):
                try:
                    data = json.loads(content)
                    return json.dumps(data, indent=2)
                except json.JSONDecodeError:
                    return content
            
            return content
        except Exception as e:
            return f"Error reading file: {str(e)}"
    
    async def _analyze(self, request: TaskAnalysisRequest) -> TaskClassificationProposal:
        """
        Analyze task and propose classification with tool support
        """
        logger.info(f"Analyzing task: {request.task_id}")
        
        # Build detailed task description
        task_details = self._build_task_details(request)
        
        # Call Claude with file reading tool available
        # Manifest is already included, but agent can read OTHER files if needed
        response = await self._model_client.create(
            [
                SystemMessage(content=self.SYSTEM_PROMPT),
                UserMessage(content=task_details, source="user")
            ],
            tools=[self._read_file_tool.schema],
            json_output=True  # Request JSON-only response for reliable parsing
        )
        
        # Check if Claude made tool calls (wants to read additional files)
        tool_calls = [item for item in response.content if isinstance(item, FunctionCall)]
        
        if tool_calls:
            logger.info(f"Claude wants to read {len(tool_calls)} additional file(s)")
            # Execute tool calls and get a second response with file contents
            # For simplicity, just log that tools were attempted
            # The classification should work with manifest content alone
            logger.warning("Tool calls detected but not executed in this simplified version")
        
        # Extract text content from response
        if isinstance(response.content, str):
            text_content = response.content
        elif isinstance(response.content, list):
            text_parts = []
            for item in response.content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif hasattr(item, 'content'):
                    text_parts.append(str(item.content))
                else:
                    text_parts.append(str(item))
            text_content = " ".join(text_parts)
        else:
            text_content = str(response.content)
        
        logger.debug(f"Extracted text content length: {len(text_content)}")
        analysis = self._parse_response(text_content)
        
        # Create proposal
        proposal = TaskClassificationProposal(
            agent_id="claude_understander",
            agent_type="claude_understander",
            core_tasks=analysis["core_tasks"],
            side_tasks=analysis["side_tasks"],
            execution_order=analysis["execution_order"],
            reasoning=analysis["reasoning"],
            confidence=analysis.get("confidence", 0.85),
            concerns=analysis.get("concerns", [])
        )
        
        logger.info(f"Claude analysis complete - {len(proposal.core_tasks)} core, {len(proposal.side_tasks)} side tasks")
        
        return proposal
    
    @message_handler
    async def handle_analysis_request(
        self,
        message: TaskAnalysisRequest,
        ctx: MessageContext
    ) -> TaskClassificationProposal:
        """Message handler that calls _analyze"""
        return await self._analyze(message)
    
    def _build_task_details(self, request: TaskAnalysisRequest) -> str:
        """Build detailed task description for analysis"""
        details = []
        
        details.append(f"TASK ID: {request.task_id}")
        details.append(f"\nTASK DESCRIPTION:")
        details.append(request.task_description)
        
        if request.files:
            details.append(f"\nFILES ({len(request.files)}):")
            for f in request.files:
                size_info = f" ({f.size_mb}MB)" if f.size_mb else ""
                details.append(f"- {f.path}{size_info}")
                if f.description:
                    details.append(f"  Description: {f.description}")
                
                # Auto-read manifest files and include content
                if f.path and (f.path.endswith('.json') or 'manifest' in f.path.lower()):
                    try:
                        file_content = self._read_file_impl(f.path)
                        if not file_content.startswith('Error'):
                            details.append(f"  Content preview (first 2000 chars):")
                            details.append(f"  {file_content[:2000]}")
                    except Exception as e:
                        logger.debug(f"Could not read file {f.path}: {e}")
        
        if request.connections:
            details.append(f"\nCONNECTIONS ({len(request.connections)}):")
            for conn in request.connections:
                details.append(f"- {conn.id} ({conn.type})")
                if conn.host:
                    details.append(f"  Host: {conn.host}")
                if conn.database:
                    details.append(f"  Database: {conn.database}")
                if conn.description:
                    details.append(f"  Description: {conn.description}")
        
        if request.constraints:
            details.append(f"\nCONSTRAINTS:")
            if request.constraints.max_duration_hours:
                details.append(f"- Max Duration: {request.constraints.max_duration_hours} hours")
            if request.constraints.max_cost_usd:
                details.append(f"- Max Cost: ${request.constraints.max_cost_usd}")
            if request.constraints.priority:
                details.append(f"- Priority: {request.constraints.priority}")
            if request.constraints.deadline:
                details.append(f"- Deadline: {request.constraints.deadline}")
        
        if request.additional_context:
            details.append(f"\nADDITIONAL CONTEXT:")
            details.append(json.dumps(request.additional_context, indent=2))
        
        details.append("\n\nProvide your technical analysis and task classification in JSON format.")
        
        return "\n".join(details)
    
    def _get_fallback_analysis(self) -> Dict:
        """Fallback analysis if parsing fails"""
        return {
            "core_tasks": [],
            "side_tasks": [],
            "execution_order": [],
            "reasoning": "Failed to generate analysis",
            "confidence": 0.0,
            "concerns": ["Analysis generation failed"]
        }
    
    def _parse_response(self, response_text: str) -> Dict:
        """Parse Claude's response into structured format"""
        # Try to extract JSON from response
        import re
        
        # Try multiple strategies to extract JSON
        json_str = None
        
        # Strategy 1: Look for JSON in code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        
        # Strategy 2: Try to find the outermost complete JSON object using greedy match
        if not json_str:
            # Find first { and last }, extract everything between
            first_brace = response_text.find('{')
            last_brace = response_text.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                json_str = response_text[first_brace:last_brace+1]
        
        # Strategy 3: Look for JSON after common phrases
        if not json_str:
            for phrase in ['here is the json:', 'json:', 'response:', 'output:']:
                idx = response_text.lower().find(phrase)
                if idx != -1:
                    remainder = response_text[idx + len(phrase):]
                    first_brace = remainder.find('{')
                    last_brace = remainder.rfind('}')
                    if first_brace != -1 and last_brace != -1:
                        json_str = remainder[first_brace:last_brace+1]
                        break
        
        if not json_str:
            # Log the response for debugging
            logger.error(f"Could not find JSON in response. First 500 chars: {response_text[:500]}")
            logger.error(f"Last 200 chars: {response_text[-200:]}")
            raise ValueError("Could not find JSON in response")
        
        # Parse JSON
        data = json.loads(json_str)
        
        # Convert to proper types
        core_tasks = [CoreTask(**task) for task in data.get("core_tasks", [])]
        side_tasks = [SideTask(**task) for task in data.get("side_tasks", [])]
        
        return {
            "core_tasks": core_tasks,
            "side_tasks": side_tasks,
            "execution_order": data.get("execution_order", []),
            "reasoning": data.get("reasoning", ""),
            "confidence": data.get("confidence", 0.85),
            "concerns": data.get("concerns", [])
        }

