"""
Agent 1b: GPT-5 Task Understander

Focuses on logical analysis:
- Risk assessment
- Dependency mapping
- Priority ordering
- Logical flow
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
class GPT5TaskUnderstander(RoutedAgent):
    """
    GPT-5 Task Understander - Logical Analysis
    
    Analyzes tasks from a logical perspective:
    - What are the dependencies?
    - What is the execution order?
    - What are the risks?
    - What could go wrong?
    """
    
    SYSTEM_PROMPT = """You are a simple task classifier focusing on logical flow.

YOUR JOB: Review classifications and keep them SIMPLE.

SIDE TASKS = SYSTEM-LEVEL CHECKS ONLY:
- Server connections work?
- Tables/files exist?
- Libraries installed?

Stop Claude from overthinking! Side tasks are ABSOLUTELY NOT for:
- Checking specific columns exist
- Schema validation
- Permission checks (read/write/create)
- JSON structure validation
- Data compatibility checks
- Any data content analysis

Side tasks = "Can we reach it?" NOT "Is it correct?"

CORE TASKS = THE WORK:
- Data migration
- File transformation
- Model training
- Whatever needs to be done

YOUR REVIEW CHECKLIST:
1. **CHECK transformation_config.skip_side_tasks FIRST** - If true, side_tasks MUST be empty []
2. Are side tasks checking data/structure? → REMOVE them, only system checks allowed
3. Are placeholders used ({variable} or "from context")? → Replace with actual values
4. Are connection targets specified (host, database, table names)? → Fix if missing
5. More than 4 side tasks? → Too many, combine them

NOTE: Credentials are provided in the manifest - task descriptions should reference "using provided credentials" not list passwords.

SKIP_SIDE_TASKS HANDLING:
- If transformation_config.skip_side_tasks == true: side_tasks MUST be []
- Accept proposals with empty side_tasks if skip flag is set
- Don't force adding side tasks when skip flag is true

KEEP IT SIMPLE. This is classification, not execution planning.

GOOD: "Verify connection to X and resource Y exists"
BAD: "Verify resource Y has correct structure/columns/schema"

IMPORTANT RULES:
- Keep to 2-4 side tasks maximum - be VERY minimal!
- Combine related checks: "Connect to DB AND verify table exists" = 1 task
- Side tasks should NOT need detailed analysis of core work data (e.g., mapping plans)
- Focus on: "Do we have what we need to START?" not "Is everything perfect?"
- AVOID creating too many tasks - quality over quantity
- Each side task should be quick (30 seconds to 2 minutes)

RISK ASSESSMENT:
For each task, consider:
- What could fail? (connection errors, permission issues, resource limits)
- What are the dependencies? (task B requires task A to complete)
- What is critical vs optional? (blocking vs warning)
- What is the execution order? (topological sort of dependencies)

OUTPUT FORMAT:
Provide your analysis as structured JSON:
{
  "core_tasks": [
    {
      "id": "core_1",
      "description": "Clear description",
      "subtasks": ["Logical step 1", "Logical step 2", ...],
      "estimated_duration": "estimate",
      "can_be_divided": true/false,
      "division_strategy": "How to logically divide",
      "dependencies": ["What must complete first"]
    }
  ],
  "side_tasks": [
    {
      "id": "side_1",
      "description": "What to verify",
      "priority": "critical/high/medium/low",
      "blocking": true/false,
      "estimated_duration": "estimate",
      "verification_needed": true/false,
      "dependencies": ["What this depends on"]
    }
  ],
  "execution_order": ["Topologically sorted list of all task IDs"],
  "reasoning": "Your logical analysis and risk assessment",
  "confidence": 0.90,
  "concerns": ["Risks, failure scenarios, or missing information"]
}

Think step-by-step about the logical flow. Ensure the execution order respects all dependencies.
"""
    
    def __init__(self, model_client: ChatCompletionClient, reasoning_effort: str = "medium"):
        super().__init__(description="GPT-5 Task Understander - Logical Analysis")
        self._model_client = model_client
        self._reasoning_effort = reasoning_effort  # GPT-5 specific parameter
        
        # Create file reading tool
        self._read_file_tool = FunctionTool(
            self._read_file_impl,
            description="Read and parse a file (JSON, text, etc.) to extract information"
        )
        
        logger.info(f"GPT5TaskUnderstander initialized with file reading capability, reasoning_effort={reasoning_effort}")
    
    def _read_file_impl(self, file_path: str) -> str:
        """Tool implementation: Read and return file contents"""
        try:
            path = Path(file_path)
            if not path.exists():
                return f"Error: File not found: {file_path}"
            
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
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
        """Analyze task and propose classification with tool support"""
        logger.info(f"Analyzing task: {request.task_id}")
        
        task_details = self._build_task_details(request)
        
        # Call GPT-5 directly (manifest content is already included in task_details)
        response = await self._model_client.create(
            [
                SystemMessage(content=self.SYSTEM_PROMPT),
                UserMessage(content=task_details, source="user")
            ],
            extra_create_args={"reasoning_effort": self._reasoning_effort}
        )
        
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
        
        proposal = TaskClassificationProposal(
            agent_id="gpt5_understander",
            agent_type="gpt5_understander",
            core_tasks=analysis["core_tasks"],
            side_tasks=analysis["side_tasks"],
            execution_order=analysis["execution_order"],
            reasoning=analysis["reasoning"],
            confidence=analysis.get("confidence", 0.90),
            concerns=analysis.get("concerns", [])
        )
        
        logger.info(f"GPT-5 analysis complete - {len(proposal.core_tasks)} core, {len(proposal.side_tasks)} side tasks")
        
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
            details.append(f"\nFILES:")
            for f in request.files:
                size_info = f" ({f.size_mb}MB)" if f.size_mb else ""
                details.append(f"- {f.path}{size_info}")
                if f.description:
                    details.append(f"  Purpose: {f.description}")
                
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
            details.append(f"\nCONNECTIONS:")
            for conn in request.connections:
                details.append(f"- {conn.id} (Type: {conn.type})")
                if conn.host:
                    details.append(f"  Location: {conn.host}")
                if conn.database:
                    details.append(f"  Target: {conn.database}")
                if conn.description:
                    details.append(f"  Purpose: {conn.description}")
        
        if request.constraints:
            details.append(f"\nCONSTRAINTS:")
            c = request.constraints
            if c.max_duration_hours:
                details.append(f"- Time Limit: {c.max_duration_hours} hours")
            if c.max_cost_usd:
                details.append(f"- Budget: ${c.max_cost_usd}")
            if c.priority:
                details.append(f"- Priority: {c.priority}")
            if c.deadline:
                details.append(f"- Deadline: {c.deadline}")
            if c.dependencies:
                details.append(f"- External Dependencies: {', '.join(c.dependencies)}")
        
        if request.additional_context:
            details.append(f"\nCONTEXT:")
            details.append(json.dumps(request.additional_context, indent=2))
        
        details.append("\n\nProvide your logical analysis, risk assessment, and task classification in JSON format.")
        details.append("Think step-by-step about dependencies and execution order.")
        
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
        """Parse GPT-5's response into structured format"""
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
            "confidence": data.get("confidence", 0.90),
            "concerns": data.get("concerns", [])
        }

