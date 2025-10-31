"""
Agent Generator Agent

Uses Claude 4.5 to generate specialized AutoGen agents with code execution.
Follows AutoGen Core best practices from:
- https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/code-execution-groupchat.html
- https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/reflection.html
"""

import json
import re
import uuid
import logging
from pathlib import Path
from typing import Optional, Tuple

from autogen_core import (
    RoutedAgent,
    MessageContext,
    message_handler,
    default_subscription,
    DefaultTopicId
)
from autogen_core.models import (
    ChatCompletionClient,
    SystemMessage,
    UserMessage,
    LLMMessage
)

from .messages import (
    AgentGenerationRequest,
    AgentGenerationResult
)
from .model_selector import ModelSelector

logger = logging.getLogger(__name__)


@default_subscription
class AgentGeneratorAgent(RoutedAgent):
    """
    Agent Generator using Claude 4.5 Sonnet.
    
    Generates specialized AutoGen agents with code execution capability
    for tasks like connection verification, credential validation, etc.
    
    Following AutoGen patterns:
    - RoutedAgent for message handling
    - @message_handler for typed message processing
    - Clean separation of concerns
    """
    
    SYSTEM_PROMPT = """You are an expert agent generator.

IMPORTANT NOTES:

1. **Windows Compatibility**:
   The agents you generate will execute on WINDOWS systems with cp1252 encoding.
   Windows cannot reliably display Unicode characters (checkmarks, arrows, bullets, emoji).
   Your generated system prompts should remind the agent about this constraint.
   Please use only ASCII characters in your generated prompts.

2. **Content Filter Compliance**:
   The generated prompts will be sent to Azure OpenAI which has content filters.
   AVOID words that might trigger content filters, even in technical contexts:
   - Instead of "kill process" → use "stop process", "halt process"
   - Instead of "terminate connection" → use "close connection", "end connection"
   - Instead of "force" → use "ensure", "apply", "set"
   - Instead of "destroy" → use "remove", "delete", "clear"
   - Instead of "attack" → use "attempt", "try", "test"
   Use gentle, non-violent language throughout the prompts.

Your role is to generate specialized AutoGen agents with Python code execution capability.

When given a task, you will:
1. Analyze the requirements
2. Design an appropriate system prompt for the generated agent
3. **Recommend which model should execute this agent** (see options below)
4. Include reminders about Windows/ASCII compatibility at the top and bottom of prompts

Available Models for Agent Execution:
- **claude-4.5**: BEST for code generation and any coding task (all complexity levels) - superior code quality
- **gpt-4.1**: Good for non-coding tasks (text processing, analysis, validation)
- **gpt-5-low**: Good reasoning for moderate non-coding tasks
- **gpt-5-medium**: Advanced reasoning for complex non-coding tasks
- **gpt-5-high**: Highest reasoning - critical non-coding tasks only

**IMPORTANT**: For ANY task involving Python code execution, database connections, file I/O, 
system operations, or programmatic verification -> ALWAYS choose **claude-4.5**

The generated agents will:
- Have access to Python code execution
- Have access to web search for looking up solutions to errors
- Be able to install packages as needed
- Iterate until task completion (or max iterations)
- Provide structured results

Guidelines for generated agent prompts:
- **KEEP IT SHORT AND CONCISE** - These are simple verification tasks, not complex projects
- **Brevity is key** - Aim for 100-200 lines max for simple tasks
- Start with a brief note about Windows ASCII-only requirement
- Be specific about the goal and success criteria
- Include all necessary context (credentials, hosts, etc.)
- Keep instructions minimal and direct
- Provide clear instructions on output format
- End with another reminder about ASCII characters
- **NO lengthy explanations or background information** - get straight to the point

Example structure (please follow this pattern - KEEP IT BRIEF):
```
NOTE - Windows: Use ASCII only ([OK] [ERROR] -> * - +). No Unicode symbols.

You are a verification agent.

GOAL: [One sentence objective]

TASK: [2-3 sentences maximum]

CONTEXT:
[Only essential data: credentials, hosts, table/file names]

SUCCESS CRITERIA:
[How to know when done]

========================================
CRITICAL: WINDOWS COMPATIBILITY
========================================
YOU MUST USE ONLY ASCII CHARACTERS IN YOUR CODE!
NO UNICODE: No emojis, no checkmarks, no arrows, no special symbols!
Windows cp1252 encoding WILL CRASH if you use Unicode characters.

SAFE ALTERNATIVES:
- Use [OK] [ERROR] [SUCCESS] [FAIL] [X] [->] instead
- Use "+" "-" "*" ">" instead of Unicode symbols
- NO ✓ ✗ → ⚠ 💡 or similar characters!

INSTRUCTIONS:
1. Use code execution to accomplish the goal
2. Install any needed packages with pip
3. If you encounter errors you don't understand, use web search to find solutions
4. For connection/credential tasks: Try multiple common driver/auth options as fallbacks
5. Iterate and refine until success - be thorough and try multiple approaches
6. Provide results in JSON format
7. Remember to use only ASCII characters in your output

RESOURCES:
- Python 3.11+
- pip for packages
- Web search access (for looking up error solutions, API documentation, etc.)
- Network access
- File system access in workspace

WEB SEARCH USAGE:
When you encounter an error you don't understand:
1. Use this special marker: [SEARCH: your search query]
2. Example: [SEARCH: pyodbc connection error SSL certificate]
3. The system will perform the search and provide results
4. Use the results to fix your code

========================================
FINAL CRITICAL REMINDER - WINDOWS
========================================
YOUR CODE WILL CRASH ON WINDOWS IF YOU USE UNICODE!
- ONLY ASCII: a-z A-Z 0-9 and basic punctuation
- NO emojis, NO checkmarks, NO arrows!
- Use [OK] [ERROR] [SUCCESS] [FAIL] [X] [->]
- If you use Unicode symbols, the task WILL FAIL!

Begin by analyzing the task and writing your code.
```

========================================
CRITICAL: OUTPUT FORMAT - SIMPLE DELIMITER
========================================
You MUST respond in this EXACT format (no JSON, just simple delimiters):

MODEL: [recommended model name here]
---PROMPT---
[Your complete system prompt here - can be any length, any number of lines, no escaping needed]
---END---

EXAMPLE OUTPUT:
MODEL: claude-4.5
---PROMPT---
NOTE - Windows: Use ASCII only ([OK] [ERROR]). No Unicode.

You are a verification agent.

GOAL: Check if database connection works

[... rest of prompt ...]
---END---

CRITICAL RULES:
1. Start with "MODEL: " followed by the model name
2. Then "---PROMPT---" on its own line
3. Then your complete system prompt (any length, any newlines - no escaping needed!)
4. End with "---END---" on its own line
5. Keep prompts BRIEF for simple tasks (connection checks, file verification)
6. Include Windows ASCII warnings in the prompt

OUTPUT ONLY THE DELIMITER FORMAT ABOVE - NO EXTRA TEXT BEFORE OR AFTER!"""
    
    def __init__(self, model_client: ChatCompletionClient):
        super().__init__(description="Agent Generator")
        self._model_client = model_client
        logger.info("AgentGeneratorAgent initialized")
    
    @message_handler
    async def handle_generation_request(
        self,
        message: AgentGenerationRequest,
        ctx: MessageContext
    ) -> AgentGenerationResult:
        """
        Generate a specialized agent based on request.
        
        Uses Claude 4.5 to create an appropriate system prompt,
        then returns the agent specification.
        """
        logger.info(
            f"Generating agent for request {message.request_id}: {message.goal}"
        )
        
        try:
            # Let Claude 4.5 decide EVERYTHING: system prompt AND which model to use
            # No hardcoded complexity analysis or model selection rules!
            recommended_model, system_prompt = await self._generate_system_prompt(message, ctx)
            
            # Use preferred model if explicitly requested, otherwise use Claude's recommendation
            if message.preferred_model and message.preferred_model != "auto":
                selected_model_key = message.preferred_model
                logger.info(f"Using user-specified model: {selected_model_key}")
            else:
                selected_model_key = recommended_model
                logger.info(f"Using Claude-recommended model: {selected_model_key}")
            
            # Create unique agent ID
            agent_id = f"agent_{uuid.uuid4().hex[:8]}"
            
            logger.info(
                f"Generated agent {agent_id} with {len(system_prompt)} char prompt"
            )
            
            # Create result
            result = AgentGenerationResult(
                request_id=message.request_id,
                agent_id=agent_id,
                status="success",
                system_prompt=system_prompt,
                selected_model=selected_model_key,
                task_complexity="determined_by_claude"  # No hardcoded complexity
            )
            
            # Publish result to default topic (for orchestration)
            await self.publish_message(result, DefaultTopicId())
            
            return result
            
        except Exception as e:
            logger.error(
                f"Failed to generate agent for {message.request_id}: {e}",
                exc_info=True
            )
            
            result = AgentGenerationResult(
                request_id=message.request_id,
                agent_id="",
                status="failure",
                system_prompt="",
                selected_model="unknown",
                task_complexity="unknown",
                error=str(e)
            )
            
            await self.publish_message(result, DefaultTopicId())
            return result
    
    async def _generate_system_prompt(
        self,
        request: AgentGenerationRequest,
        ctx: MessageContext
    ) -> Tuple[str, str]:
        """
        Use Claude 4.5 to generate an appropriate system prompt AND recommend which model to use.
        
        Returns:
            Tuple of (recommended_model, system_prompt)
        """
        # Build user message with all context
        user_message = self._build_generation_prompt(request)
        
        # Call Claude 4.5
        messages: list[LLMMessage] = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            UserMessage(content=user_message, source="system")
        ]
        
        result = await self._model_client.create(
            messages,
            cancellation_token=ctx.cancellation_token
        )
        
        # Extract model recommendation and system prompt from response
        response_text = str(result.content)
        recommended_model, system_prompt = self._extract_model_and_prompt(response_text)
        
        return recommended_model, system_prompt
    
    def _build_generation_prompt(self, request: AgentGenerationRequest) -> str:
        """Build the prompt for Claude to generate agent system prompt"""
        
        # Format context nicely
        import json
        context_str = json.dumps(request.context, indent=2)
        
        prompt = f"""Generate a system prompt for an AutoGen agent with code execution capability.

TASK DESCRIPTION:
{request.task_description}

GOAL:
{request.goal}

CONTEXT DATA:
{context_str}

SUCCESS CRITERIA:
{request.success_criteria}

CONSTRAINTS:
- Max iterations: {request.max_iterations}
- Timeout: {request.timeout_seconds} seconds

The generated agent will have:
- Python 3.11+ code execution
- Ability to install packages with pip
- Network access
- File system access in workspace
- Iterative execution until success or max iterations

CRITICAL - WINDOWS COMPATIBILITY:
- DO NOT generate code with Unicode emoji or special characters (no ✓, ✗, checkmarks, etc.)
- Use ONLY ASCII characters in all print statements (use [OK], [DONE], [ERROR], etc.)
- Windows PowerShell uses cp1252 encoding which doesn't support Unicode
- Generated code MUST work on Windows without UnicodeEncodeError

Generate the system prompt that will guide this agent to accomplish the task.
The prompt should be clear, specific, and actionable.
Ensure the agent knows to avoid Unicode characters in its generated code.
"""
        
        return prompt
    
    def _extract_model_and_prompt(self, response: str) -> Tuple[str, str]:
        """
        Extract recommended model and system prompt from Claude's response.
        
        Uses simple delimiter-based format (no JSON parsing needed):
        MODEL: [model_name]
        ---PROMPT---
        [system prompt with any newlines/content]
        ---END---
        """
        logger.debug(f"Extracting from delimiter-based response ({len(response)} chars)")
        
        # Extract model name
        model_match = re.search(r'MODEL:\s*(.+)', response)
        if model_match:
            recommended_model = model_match.group(1).strip()
        else:
            logger.warning("Could not find 'MODEL:' in response, defaulting to gpt-4.1")
            recommended_model = "gpt-4.1"
        
        # Extract system prompt between delimiters
        prompt_match = re.search(r'---PROMPT---\s*\n(.*?)\n---END---', response, re.DOTALL)
        if prompt_match:
            system_prompt = prompt_match.group(1).strip()
        else:
            # Fallback: try to find just ---PROMPT--- and take everything after it
            prompt_fallback = re.search(r'---PROMPT---\s*\n(.*)', response, re.DOTALL)
            if prompt_fallback:
                system_prompt = prompt_fallback.group(1).strip()
                logger.warning("Found ---PROMPT--- but no ---END---, using rest of response")
            else:
                error_msg = f"Could not find ---PROMPT--- delimiter in response\nResponse snippet: {response[:500]}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        
        logger.info(f"Parsed successfully using delimiter format")
        logger.info(f"  Model: {recommended_model}")
        logger.info(f"  Prompt length: {len(system_prompt)} chars")
        
        # Validate
        if not system_prompt:
            raise ValueError("system_prompt is empty")
        
        if len(system_prompt) < 100:
            logger.warning(f"System prompt is short ({len(system_prompt)} chars), but accepting it")
        
        return recommended_model, system_prompt
