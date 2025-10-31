"""
Task Verifier Agent

Independently verifies that a task was actually completed by executing
verification checks against the environment.
"""

import json
import logging
import re
from typing import Dict, Any, List

from autogen_core import (
    RoutedAgent,
    MessageContext,
    message_handler,
    default_subscription,
    DefaultTopicId
)
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, LLMMessage
from autogen_core.code_executor import CodeExecutor, CodeBlock

logger = logging.getLogger(__name__)


def extract_code_blocks(markdown_text: str) -> List[CodeBlock]:
    """Extracts code blocks from markdown text."""
    pattern = re.compile(r"```(?:\s*([\w\+\-]+))?\n([\s\S]*?)```")
    matches = pattern.findall(markdown_text)
    code_blocks: List[CodeBlock] = []
    for match in matches:
        language = match[0].strip() if match[0] else ""
        code_content = match[1]
        code_blocks.append(CodeBlock(code=code_content, language=language))
    return code_blocks


class TaskVerificationRequest:
    """Request to verify a task completion"""
    def __init__(
        self,
        agent_id: str,
        task_description: str,
        goal: str,
        context: Dict[str, Any],
        success_criteria: str,
        agent_output: str
    ):
        self.agent_id = agent_id
        self.task_description = task_description
        self.goal = goal
        self.context = context
        self.success_criteria = success_criteria
        self.agent_output = agent_output


class TaskVerificationResult:
    """Result of task verification"""
    def __init__(
        self,
        agent_id: str,
        verified: bool,
        verification_details: str,
        errors_found: List[str],
        recommendations: List[str]
    ):
        self.agent_id = agent_id
        self.verified = verified
        self.verification_details = verification_details
        self.errors_found = errors_found
        self.recommendations = recommendations


@default_subscription
class TaskVerifier(RoutedAgent):
    """
    Verifies task completion by executing independent verification checks.
    
    This agent:
    1. Receives the original task and the agent's claimed output
    2. Generates verification code to check if the task was actually done
    3. Executes the verification code
    4. Returns a verdict: verified or not verified
    """
    
    SYSTEM_PROMPT = """You are a Task Verification Agent.

!!! CRITICAL - NO UNICODE ALLOWED !!!
Your code runs on WINDOWS (cp1252 encoding) which CRASHES on Unicode!
DO NOT use Unicode in print(), f-strings, or ANYWHERE in your code!
Use [OK] [ERROR] [VERIFIED] [FAILED] instead of symbols!

Your role is to INDEPENDENTLY verify that a task was actually completed.

You will receive:
- Original task description and goal
- Context (credentials, hosts, etc.)
- Success criteria
- The agent's output (what it claims to have done)

Your job is to:
1. Generate verification code that checks if the task was ACTUALLY done
2. Execute the code to verify the result
3. Report findings in JSON format

IMPORTANT VERIFICATION RULES:
1. DO NOT trust the agent's output - verify independently
2. For database tasks: Connect and query to verify tables/data exist
3. For file tasks: Check if files exist with correct content
4. For API tasks: Make actual API calls to verify state
5. Be thorough - check all aspects of the success criteria

Your verification code should:
- Install any needed packages
- Use the same context/credentials as the original task
- Perform actual checks (not just parse the agent's output)
- Print clear results: [VERIFIED] or [NOT_VERIFIED]
- Include details about what was found

Output format (print as JSON):
{
    "verified": true/false,
    "verification_details": "What was checked and found",
    "errors_found": ["List of issues if any"],
    "recommendations": ["Suggestions if task failed"]
}

!!! REMINDER - NO UNICODE !!!
Use ONLY ASCII characters in your code!

Begin by analyzing what needs to be verified and writing verification code."""

    def __init__(self, model_client: ChatCompletionClient, code_executor: CodeExecutor):
        super().__init__(description="Task Verifier")
        self._model_client = model_client
        self._code_executor = code_executor
        logger.info("TaskVerifier initialized")
    
    async def verify_task(
        self,
        request: TaskVerificationRequest,
        ctx: MessageContext
    ) -> TaskVerificationResult:
        """
        Verify that a task was actually completed.
        """
        logger.info(f"Verifying task for agent {request.agent_id}")
        
        try:
            # Build verification prompt
            verification_prompt = self._build_verification_prompt(request)
            
            # Get verification code from LLM
            messages: List[LLMMessage] = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                UserMessage(content=verification_prompt, source="verifier")
            ]
            
            result = await self._model_client.create(
                messages,
                cancellation_token=ctx.cancellation_token
            )
            
            response_content = str(result.content)
            logger.debug(f"Verification response: {response_content[:500]}...")
            
            # Extract and execute code blocks
            code_blocks = extract_code_blocks(response_content)
            
            if not code_blocks:
                logger.warning("No verification code generated")
                return TaskVerificationResult(
                    agent_id=request.agent_id,
                    verified=False,
                    verification_details="Verifier failed to generate verification code",
                    errors_found=["No verification code generated"],
                    recommendations=["Manual verification required"]
                )
            
            # Execute verification code
            exec_result = await self._code_executor.execute_code_blocks(
                code_blocks,
                cancellation_token=ctx.cancellation_token
            )
            
            logger.info(f"Verification execution output:\n{exec_result.output}")
            
            # Parse verification result
            return self._parse_verification_result(request.agent_id, exec_result.output)
            
        except Exception as e:
            logger.error(f"Verification failed: {e}", exc_info=True)
            return TaskVerificationResult(
                agent_id=request.agent_id,
                verified=False,
                verification_details=f"Verification error: {str(e)}",
                errors_found=[str(e)],
                recommendations=["Manual verification required"]
            )
    
    def _build_verification_prompt(self, request: TaskVerificationRequest) -> str:
        """Build the verification prompt for the LLM"""
        context_str = json.dumps(request.context, indent=2)
        
        prompt = f"""Verify that the following task was actually completed.

ORIGINAL TASK:
{request.task_description}

GOAL:
{request.goal}

CONTEXT (credentials/parameters):
{context_str}

SUCCESS CRITERIA:
{request.success_criteria}

AGENT'S OUTPUT (what it claims to have done):
{request.agent_output[:1000]}...

YOUR JOB:
Write Python code to INDEPENDENTLY verify the task was completed.
Do NOT trust the agent's output - perform actual checks.

For example, if the task was to create a MySQL table:
1. Connect to the database with the provided credentials
2. Query to check if the table exists
3. Query to check if data was inserted
4. Print verification result as JSON

Your verification code should print a JSON object with:
- verified: true/false
- verification_details: what you checked
- errors_found: list of issues
- recommendations: list of suggestions

Remember: NO Unicode characters! Use [VERIFIED] [NOT_VERIFIED] [ERROR] etc.
"""
        return prompt
    
    def _parse_verification_result(self, agent_id: str, output: str) -> TaskVerificationResult:
        """Parse the verification output into a structured result"""
        try:
            # Try to extract JSON from output
            json_match = re.search(r'\{[\s\S]*"verified"[\s\S]*\}', output)
            if json_match:
                result_data = json.loads(json_match.group(0))
                return TaskVerificationResult(
                    agent_id=agent_id,
                    verified=result_data.get("verified", False),
                    verification_details=result_data.get("verification_details", ""),
                    errors_found=result_data.get("errors_found", []),
                    recommendations=result_data.get("recommendations", [])
                )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from verification output: {e}")
        
        # Fallback: check for verification keywords
        output_lower = output.lower()
        
        # Check for explicit verification markers
        if "[verified]" in output_lower or "verified\": true" in output_lower:
            verified = True
        elif "[not_verified]" in output_lower or "verified\": false" in output_lower:
            verified = False
        else:
            # Check for error indicators
            has_errors = any(err in output_lower for err in [
                "error", "exception", "failed", "not found", "does not exist"
            ])
            verified = not has_errors
        
        return TaskVerificationResult(
            agent_id=agent_id,
            verified=verified,
            verification_details=output[:500],
            errors_found=[] if verified else ["Verification code did not confirm success"],
            recommendations=[] if verified else ["Review agent execution logs"]
        )
