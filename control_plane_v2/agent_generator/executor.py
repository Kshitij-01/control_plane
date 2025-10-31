"""
Generated Agent Executor

Executes dynamically generated agents using AutoGen's code execution patterns.
Based on: https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/code-execution-groupchat.html
"""

import re
import time
import logging
from typing import List, Optional
from pathlib import Path

from autogen_core import (
    RoutedAgent,
    MessageContext,
    message_handler,
    default_subscription,
    DefaultTopicId
)
from autogen_core.code_executor import CodeBlock, CodeExecutor
from autogen_core.models import (
    ChatCompletionClient,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    LLMMessage
)

from .messages import (
    AgentExecutionRequest,
    AgentExecutionResult
)

logger = logging.getLogger(__name__)


def extract_code_blocks(text: str) -> List[CodeBlock]:
    """
    Extract code blocks from markdown text.
    
    Adapted from AutoGen's code execution pattern.
    """
    pattern = re.compile(r'```(?:\s*([\w\+\-]+))?\n([\s\S]*?)```')
    matches = pattern.findall(text)
    
    code_blocks: List[CodeBlock] = []
    for match in matches:
        language = match[0].strip() if match[0] else "python"
        code_content = match[1]
        code_blocks.append(CodeBlock(code=code_content, language=language))
    
    return code_blocks


@default_subscription
class GeneratedAgentExecutor(RoutedAgent):
    """
    Executes generated agents with code execution capability.
    
    Follows AutoGen's Assistant + Executor pattern:
    - Agent generates code
    - Executor runs code
    - Iterate until success
    
    Reference: https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/code-execution-groupchat.html
    """
    
    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        model_client: ChatCompletionClient,
        code_executor: CodeExecutor,
        max_iterations: int = 10,
        tools: Optional[List] = None
    ):
        super().__init__(description=f"Executor for {agent_id}")
        self._agent_id = agent_id
        self._system_prompt = system_prompt
        self._model_client = model_client
        self._code_executor = code_executor
        self._max_iterations = max_iterations
        self._tools = tools or []
        self._chat_history: List[LLMMessage] = []
        
        logger.info(f"GeneratedAgentExecutor created for {agent_id} with {len(self._tools)} tools")
    
    def _extract_search_query(self, text: str) -> Optional[str]:
        """Extract search query from [SEARCH: ...] marker."""
        match = re.search(r'\[SEARCH:\s*(.+?)\]', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
    
    async def _perform_web_search(self, query: str) -> str:
        """
        Perform web search and return formatted results.
        
        Supports multiple search providers:
        1. Tavily (AI-optimized, preferred)
        2. SerpAPI (fallback)
        3. DuckDuckGo (free fallback)
        """
        try:
            import asyncio
            from urllib.parse import quote
            import os
            
            logger.info(f"Web search requested: {query}")
            
            # Try Tavily first (designed for AI agents)
            tavily_key = os.getenv('TAVILY_API_KEY')
            if tavily_key:
                try:
                    return await self._search_tavily(query, tavily_key)
                except Exception as e:
                    logger.warning(f"Tavily search failed: {e}")
            
            # Try SerpAPI as fallback
            serpapi_key = os.getenv('SERPAPI_KEY')
            if serpapi_key:
                try:
                    return await self._search_serpapi(query, serpapi_key)
                except Exception as e:
                    logger.warning(f"SerpAPI search failed: {e}")
            
            # Try DuckDuckGo as free fallback
            try:
                return await self._search_duckduckgo(query)
            except Exception as e:
                logger.warning(f"DuckDuckGo search failed: {e}")
            
            # If all fail, return helpful guidance
            return self._search_fallback_message(query)
            
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return f"[ERROR] Web search failed: {e}\nPlease continue without search results."
    
    async def _search_tavily(self, query: str, api_key: str) -> str:
        """Search using Tavily API (AI-optimized)."""
        try:
            from tavily import TavilyClient
        except ImportError:
            logger.info("tavily-python not installed, attempting to install...")
            import subprocess
            subprocess.run(["pip", "install", "-q", "tavily-python"], check=True)
            from tavily import TavilyClient
        
        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=5)
        
        results = []
        results.append("=== WEB SEARCH RESULTS (Tavily) ===")
        results.append(f"Query: {query}\n")
        
        for i, item in enumerate(response.get('results', []), 1):
            results.append(f"{i}. {item.get('title', 'No title')}")
            results.append(f"   URL: {item.get('url', '')}")
            results.append(f"   {item.get('content', '')[:300]}...")
            results.append("")
        
        results.append("===========================")
        return "\n".join(results)
    
    async def _search_serpapi(self, query: str, api_key: str) -> str:
        """Search using SerpAPI."""
        import requests
        
        params = {
            'q': query,
            'api_key': api_key,
            'engine': 'google',
            'num': 5
        }
        
        response = requests.get('https://serpapi.com/search', params=params, timeout=10)
        data = response.json()
        
        results = []
        results.append("=== WEB SEARCH RESULTS (SerpAPI) ===")
        results.append(f"Query: {query}\n")
        
        for i, item in enumerate(data.get('organic_results', [])[:5], 1):
            results.append(f"{i}. {item.get('title', 'No title')}")
            results.append(f"   URL: {item.get('link', '')}")
            results.append(f"   {item.get('snippet', '')}")
            results.append("")
        
        results.append("===========================")
        return "\n".join(results)
    
    async def _search_duckduckgo(self, query: str) -> str:
        """Search using DuckDuckGo (free, no API key needed)."""
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                # Try old package name
                from duckduckgo_search import DDGS
            except ImportError:
                logger.info("ddgs not installed, attempting to install...")
                import subprocess
                subprocess.run(["pip", "install", "-q", "ddgs"], check=True)
                from ddgs import DDGS
        
        ddgs = DDGS()
        search_results = list(ddgs.text(query, max_results=5))
        
        results = []
        results.append("=== WEB SEARCH RESULTS (DuckDuckGo) ===")
        results.append(f"Query: {query}\n")
        
        for i, item in enumerate(search_results, 1):
            results.append(f"{i}. {item.get('title', 'No title')}")
            results.append(f"   URL: {item.get('href', '')}")
            results.append(f"   {item.get('body', '')}")
            results.append("")
        
        results.append("===========================")
        return "\n".join(results)
    
    def _search_fallback_message(self, query: str) -> str:
        """Return helpful message when no search API is available."""
        return f"""
=== WEB SEARCH (No API Configured) ===
Query: {query}

[INFO] To enable web search, set one of these environment variables:
- TAVILY_API_KEY (recommended for AI agents - get free key at tavily.com)
- SERPAPI_KEY (get at serpapi.com)
- Or install duckduckgo-search for free searches: pip install duckduckgo-search

For now, here are common solutions for your query:

Common Error Solutions:
- Import errors: Install the package with pip
- Connection errors: Check credentials, host, port, SSL settings
- SSL errors: Try TrustServerCertificate=yes or ssl_disabled=True for testing
- Driver errors: Install required drivers or try alternative libraries
- Timeout errors: Increase timeout value or check network connectivity

Best Practices:
1. Read error messages carefully - they usually contain the solution
2. Check package documentation for correct usage
3. Try simpler connection strings first, then add options
4. Use try-except blocks to handle errors gracefully

Continue with your best approach based on the error message.
===========================
"""
    
    @message_handler
    async def handle_execution_request(
        self,
        message: AgentExecutionRequest,
        ctx: MessageContext
    ) -> AgentExecutionResult:
        """
        Execute the agent iteratively until task complete.
        
        Implements iterative execution:
        1. Agent generates code
        2. Execute code
        3. Send results back to agent
        4. Repeat until success or max iterations
        """
        if message.agent_id != self._agent_id:
            # Not for this agent
            return None  # type: ignore
        
        logger.info(f"Executing agent {self._agent_id}")
        start_time = time.time()
        
        try:
            # Initialize chat history
            self._chat_history = [
                SystemMessage(content=self._system_prompt),
                UserMessage(content=message.message, source="user")
            ]
            
            # Iterative execution loop
            iteration = 0
            last_output = ""
            task_completed = False  # Require proof of success
            full_execution_log = []  # Track all execution outputs
            
            while iteration < self._max_iterations:
                iteration += 1
                logger.info(f"Agent {self._agent_id} - Iteration {iteration}")
                
                # Get agent response
                result = await self._model_client.create(
                    self._chat_history,
                    tools=self._tools if self._tools else None,
                    cancellation_token=ctx.cancellation_token
                )
                
                response_content = str(result.content)
                logger.debug(
                    f"Agent {self._agent_id} response:\n{response_content[:500]}..."
                )
                
                # Add to history
                self._chat_history.append(
                    AssistantMessage(content=response_content, source="assistant")
                )
                
                # Check for web search request
                search_query = self._extract_search_query(response_content)
                if search_query:
                    logger.info(f"Agent {self._agent_id} requested web search: {search_query}")
                    search_results = await self._perform_web_search(search_query)
                    self._chat_history.append(
                        UserMessage(content=search_results, source="web_search")
                    )
                    # Continue to next iteration to let agent use search results
                    continue
                
                # Check if agent is done (no code blocks means reflection/summary)
                code_blocks = extract_code_blocks(response_content)
                
                if not code_blocks:
                    # If this is early iteration, agent might be planning/thinking
                    if iteration <= 2:
                        logger.warning(
                            f"Agent {self._agent_id} did not generate code on iteration {iteration} - continuing"
                        )
                        # Add a prompt to encourage code generation
                        self._chat_history.append(UserMessage(
                            content="Please write and execute Python code now (not explanations). Use code blocks with ```python",
                            source="user"
                        ))
                        last_output = response_content
                        continue  # Try again in next iteration
                    else:
                        # Agent provided summary/conclusion after executing code
                        logger.info(
                            f"Agent {self._agent_id} concluded (no code blocks)"
                        )
                        last_output = response_content
                        break
                
                # Execute code blocks
                exec_result = await self._code_executor.execute_code_blocks(
                    code_blocks,
                    cancellation_token=ctx.cancellation_token
                )
                
                last_output = exec_result.output
                full_execution_log.append(f"=== Iteration {iteration} ===\n{last_output}\n")
                
                logger.info(
                    f"Execution output:\n{last_output[:500]}..."
                )
                
                # Check for errors in execution output
                has_errors = self._check_for_errors(exec_result.output)
                
                # Send execution result back to agent with error context
                if has_errors:
                    feedback = f"Execution result (ERRORS DETECTED - Please fix and retry):\n{exec_result.output}"
                    logger.warning(f"Agent {self._agent_id} - Errors detected in iteration {iteration}")
                else:
                    feedback = f"Execution result:\n{exec_result.output}"
                
                self._chat_history.append(
                    UserMessage(
                        content=feedback,
                        source="executor"
                    )
                )
                
                # Only check completion if no errors
                if not has_errors and self._check_completion(exec_result.output):
                    logger.info(
                        f"Agent {self._agent_id} task appears complete (no errors, success indicators found)"
                    )
                    task_completed = True  # Explicitly mark as completed
                    break
            
            duration = time.time() - start_time
            
            # After loop completes, verify files for logging (not blocking)
            if task_completed:
                file_check = self._verify_expected_files(message.message, last_output)
                if not file_check:
                    logger.warning(f"Agent {self._agent_id} completed but some expected files may be missing (check logs above)")
            
            # Determine final status based on task completion
            final_status = "completed" if task_completed else "failed"
            
            # Create full output with all execution logs
            full_output = "\n".join(full_execution_log) if full_execution_log else last_output
            
            # Create result
            result = AgentExecutionResult(
                agent_id=self._agent_id,
                status=final_status,
                output=full_output,
                iterations=iteration,
                duration_seconds=duration,
                error=None if task_completed else "Task completion not verified - no success indicators found in execution output"
            )
            
            # Publish result
            await self.publish_message(result, DefaultTopicId())
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Agent {self._agent_id} execution failed: {e}",
                exc_info=True
            )
            
            result = AgentExecutionResult(
                agent_id=self._agent_id,
                status="failed",
                output=last_output if 'last_output' in locals() else "",
                iterations=iteration if 'iteration' in locals() else 0,
                duration_seconds=duration,
                error=str(e)
            )
            
            await self.publish_message(result, DefaultTopicId())
            return result
    
    def _check_for_errors(self, output: str) -> bool:
        """
        Check if execution output contains errors.

        Detects Python exceptions, SQL errors, connection errors, etc.
        """
        error_indicators = [
            "error",
            "exception",
            "traceback",
            "failed",
            "failure",
            "errno",
            "syntaxerror",
            "typeerror",
            "valueerror",
            "attributeerror",
            "keyerror",
            "indexerror",
            "runtimeerror",
            "connectionerror",
            "timeouterror",
            # MySQL/Database errors
            "mysql.connector.errors",
            "access denied",
            "unknown database",
            "table doesn't exist",
            "can't connect to mysql",
            "lost connection",
            # General SQL errors
            "sqlexception",
            "database error",
            "query failed",
            # File/IO errors
            "filenotfounderror",
            "permissionerror",
            "ioerror",
            # Network errors
            "connection refused",
            "timeout",
            "unreachable",
        ]

        output_lower = output.lower()

        # Check for error indicators
        has_error_keywords = any(indicator in output_lower for indicator in error_indicators)

        # Additional checks
        has_traceback = "traceback (most recent call last)" in output_lower
        has_raised_exception = "raised" in output_lower and "exception" in output_lower
        
        # Check for MySQL specific errors
        has_mysql_error = "error" in output_lower and ("mysql" in output_lower or "1045" in output or "2003" in output)

        return has_error_keywords or has_traceback or has_raised_exception or has_mysql_error
    
    def _check_completion(self, output: str) -> bool:
        """
        Check if execution output indicates task completion.
        
        Requires BOTH:
        1. Explicit success/completion message
        2. Some form of verification output (query results, table data, etc.)
        
        NOTE: This is case-insensitive to handle agents that use uppercase markers
        """
        output_lower = output.lower()
        
        # Require explicit success indicator (all lowercase for case-insensitive matching)
        success_indicators = [
            '"status": "success"',
            "'status': 'success'",
            '"status": "[success]"',
            "[success]",
            "successfully created",
            "successfully inserted",
            "verified successfully",
            "verification passed",
            "verification complete",
            "task completed",
            "table exists",
            "data inserted",
            "[done]",  # matches [DONE] when lowercased
            "[ok]",    # matches [OK] when lowercased
            "[final result]",
            "results saved",  # common pattern from agents
        ]
        
        has_success_indicator = any(indicator in output_lower for indicator in success_indicators)
        
        # Also require some evidence of actual work (not just print statements)
        # For SQL tasks
        sql_evidence = ["select", "insert", "create table", "describe", "rows", "column", "table exists", "query"]
        # For file tasks
        file_evidence = ["file exists", "file created", "content verified", "file_path", "content:", "written"]
        # Combined
        evidence_indicators = sql_evidence + file_evidence
        
        has_evidence = any(indicator in output_lower for indicator in evidence_indicators)
        
        # Require BOTH
        return has_success_indicator and has_evidence
    
    def _verify_expected_files(self, task_description: str, output: str) -> bool:
        """
        Verify that expected files exist if task mentions file creation.
        
        Args:
            task_description: Original task description
            output: Execution output
            
        Returns:
            True if no files expected OR all expected files exist
            False if files expected but missing
        """
        # Extract expected file names from task description and output
        import re
        
        # Look for patterns like "save to X.json", "create X.json", "write X.json"
        file_patterns = [
            r'save (?:to|results to)\s+(\w+\.json)',
            r'create\s+(?:a\s+)?(?:file\s+)?(?:named\s+)?(\w+\.json)',
            r'write\s+(?:to\s+)?(\w+\.json)',
            r'side_task_(\d+)\.json',
        ]
        
        expected_files = []
        for pattern in file_patterns:
            matches = re.findall(pattern, task_description.lower())
            expected_files.extend(matches)
            
            matches = re.findall(pattern, output.lower())
            expected_files.extend(matches)
        
        # If no files mentioned, pass the check
        if not expected_files:
            logger.debug("No expected files mentioned in task, skipping file verification")
            return True
        
        # Check if files exist in code executor's working directory
        # The code executor runs in a subdirectory, so check there
        import os
        from pathlib import Path
        
        # Get current working directory (where code executes)
        work_dir = self._code_executor._work_dir if hasattr(self._code_executor, '_work_dir') else Path.cwd()
        
        all_exist = True
        for filename in set(expected_files):
            # Handle both full filenames and just task numbers
            if filename.isdigit():
                filename = f"side_task_{filename}.json"
            
            file_path = work_dir / filename
            exists = file_path.exists()
            
            if exists:
                logger.info(f"File verification PASS: {filename} exists at {file_path}")
            else:
                logger.warning(f"File verification FAIL: {filename} NOT found at {file_path}")
                all_exist = False
        
        return all_exist
