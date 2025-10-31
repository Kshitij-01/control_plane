"""
Phase 1: Core Task Divider

Analyzes core tasks and breaks them down into executable subtasks with proper orchestration.
Uses Claude 4.5 for intelligent task decomposition.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from autogen_core import MessageContext
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage

from .messages import TaskDivisionRequest, TaskDivisionResult, Subtask

logger = logging.getLogger(__name__)


class TaskDivider:
    """
    Intelligent task divider using Claude 4.5
    
    Analyzes core tasks and their associated plans (JSON files) to determine
    if they can be broken down into smaller, manageable subtasks.
    """
    
    SYSTEM_PROMPT = """You are an intelligent task decomposition agent.

YOUR JOB: Analyze tasks and their plans, decide if they should be broken into subtasks.

INPUT:
- Core task description
- JSON plan file (mapping rules, config, workflow, etc.)
- Credentials and context

OUTPUT: JSON with task division decision

PRINCIPLES:
1. **Keep it simple** - Don't over-decompose
2. **Logical chunks** - Break at natural boundaries (files, stages, resources)
3. **Dependencies** - Identify what must run before what
4. **General purpose** - Works for migrations, transformations, ML, deployments, etc.

WHEN TO DIVIDE:
✅ Multiple independent resources (files, tables, APIs)
✅ Clear stages (extract -> transform -> load)
✅ Large datasets that benefit from chunking
✅ Parallel-safe operations

WHEN NOT TO DIVIDE:
❌ Simple single-step tasks
❌ Operations that must be atomic
❌ Task is already specific enough

EXAMPLES:

Example 1 - DIVIDE:
Task: "Process data using configuration plan"
Plan: {operations: [{op_type: "extract_A"}, {op_type: "extract_B"}, {op_type: "merge_AB"}]}
→ Subtask 1: Extract dataset A
→ Subtask 2: Extract dataset B (parallel with Subtask 1)
→ Subtask 3: Merge A and B (depends on Subtasks 1 & 2)

Example 2 - DON'T DIVIDE:
Task: "Clean temporary files in /tmp"
Plan: {patterns: ["*.tmp", "*.cache"]}
→ Single subtask: This is already specific, no need to break down

Example 3 - DIVIDE BY STAGES:
Task: "ETL pipeline for sales data"
Plan: {source: "s3://raw", transform: "normalize", dest: "warehouse"}
→ Subtask 1: Extract from S3
→ Subtask 2: Transform data (depends on 1)
→ Subtask 3: Load to warehouse (depends on 2)

OUTPUT FORMAT (JSON):
{
  "can_be_divided": true/false,
  "reasoning": "why or why not to divide",
  "subtasks": [
    {
      "id": "subtask_1",
      "description": "Clear, specific description with all details",
      "dependencies": [],
      "estimated_duration": "5-10 minutes",
      "complexity": "simple/moderate/complex",
      "inputs_required": {"file": "path", "creds": "..."},
      "outputs_produced": ["result_file", "log"]
    }
  ],
  "execution_strategy": "sequential/parallel/dag",
  "estimated_total_duration": "10-20 minutes",
  "confidence": 0.85,
  "warnings": ["any concerns or risks"]
}

REMEMBER: Be practical, not pedantic. If it's simple, keep it simple!
"""
    
    def __init__(self, model_client: ChatCompletionClient):
        self._model_client = model_client
        logger.info("TaskDivider initialized with Claude 4.5")
    
    async def divide_task(self, request: TaskDivisionRequest) -> TaskDivisionResult:
        """
        Analyze core task and decide if/how to divide it into subtasks
        
        Args:
            request: Task division request with core task and plan
            
        Returns:
            TaskDivisionResult with subtasks (if divided) or single task (if not)
        """
        logger.info(f"Analyzing task for division: {request.task_id}")
        
        # Load plan content if file path provided
        plan_content = request.plan_content
        if request.plan_file_path and not plan_content:
            plan_content = self._load_plan_file(request.plan_file_path)
        
        # Build analysis prompt
        prompt = self._build_analysis_prompt(request, plan_content)
        
        # Get Claude's analysis
        logger.info("Requesting task division analysis from Claude 4.5...")
        response = await self._model_client.create([
            SystemMessage(content=self.SYSTEM_PROMPT),
            UserMessage(content=prompt, source="user")
        ])
        
        # Parse response
        result = self._parse_division_response(str(response.content), request.task_id)
        
        logger.info(f"Division complete: can_be_divided={result.can_be_divided}, "
                   f"subtasks={len(result.subtasks)}, strategy={result.execution_strategy}")
        
        return result
    
    def _load_plan_file(self, file_path: str) -> Dict[str, Any]:
        """Load and parse JSON plan file"""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load plan file {file_path}: {e}")
            return {}
    
    def _build_analysis_prompt(
        self,
        request: TaskDivisionRequest,
        plan_content: Optional[Dict[str, Any]]
    ) -> str:
        """Build detailed analysis prompt for Claude"""
        lines = []
        
        lines.append("TASK DIVISION REQUEST")
        lines.append("=" * 60)
        lines.append(f"\nTask ID: {request.task_id}")
        lines.append(f"Core Task: {request.core_task_description}")
        
        if request.success_criteria:
            lines.append(f"Success Criteria: {request.success_criteria}")
        
        if plan_content:
            lines.append(f"\nPlan Content ({len(str(plan_content))} bytes):")
            lines.append(json.dumps(plan_content, indent=2))
        elif request.plan_file_path:
            lines.append(f"\nPlan File: {request.plan_file_path}")
        
        if request.connections:
            lines.append(f"\nAvailable Connections: {len(request.connections)}")
            for conn in request.connections:
                lines.append(f"  - {conn.get('type', 'unknown')}: {conn.get('id', 'N/A')}")
        
        if request.additional_context:
            lines.append(f"\nAdditional Context:")
            for key, value in request.additional_context.items():
                if isinstance(value, (str, int, float, bool)):
                    lines.append(f"  - {key}: {value}")
        
        lines.append("\n" + "=" * 60)
        lines.append("ANALYZE THE ABOVE AND PROVIDE YOUR DIVISION DECISION")
        lines.append("Respond with JSON only (no explanations before/after)")
        
        return "\n".join(lines)
    
    def _parse_division_response(self, response_text: str, task_id: str) -> TaskDivisionResult:
        """Parse Claude's JSON response into TaskDivisionResult"""
        try:
            # Extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                logger.error("No JSON found in response")
                return self._create_fallback_result(task_id, "Failed to parse response")
            
            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)
            
            # Parse subtasks
            subtasks = []
            for st in data.get("subtasks", []):
                subtasks.append(Subtask(
                    id=st.get("id", f"subtask_{len(subtasks)+1}"),
                    description=st.get("description", ""),
                    dependencies=st.get("dependencies", []),
                    estimated_duration=st.get("estimated_duration", "unknown"),
                    complexity=st.get("complexity", "moderate"),
                    inputs_required=st.get("inputs_required", {}),
                    outputs_produced=st.get("outputs_produced", [])
                ))
            
            return TaskDivisionResult(
                task_id=task_id,
                can_be_divided=data.get("can_be_divided", False),
                reasoning=data.get("reasoning", ""),
                subtasks=subtasks,
                execution_strategy=data.get("execution_strategy", "sequential"),
                estimated_total_duration=data.get("estimated_total_duration", "unknown"),
                confidence=data.get("confidence", 0.0),
                warnings=data.get("warnings", [])
            )
            
        except Exception as e:
            logger.error(f"Failed to parse division response: {e}")
            logger.debug(f"Response text: {response_text[:500]}...")
            return self._create_fallback_result(task_id, str(e))
    
    def _create_fallback_result(self, task_id: str, error: str) -> TaskDivisionResult:
        """Create fallback result when parsing fails"""
        return TaskDivisionResult(
            task_id=task_id,
            can_be_divided=False,
            reasoning=f"Error analyzing task: {error}. Treating as single task.",
            subtasks=[],
            execution_strategy="sequential",
            confidence=0.0,
            warnings=[f"Division analysis failed: {error}"]
        )

