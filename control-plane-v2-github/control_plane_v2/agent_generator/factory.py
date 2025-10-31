"""
Agent Factory

Manages the lifecycle of dynamically generated agents.
Follows AutoGen best practices for agent management.
"""

import shutil
import logging
from pathlib import Path
from typing import Dict, Optional, List

from autogen_core import SingleThreadedAgentRuntime, AgentId
from autogen_core.models import ChatCompletionClient
from autogen_ext.code_executors import LocalCommandLineCodeExecutor

from .messages import (
    AgentGenerationRequest,
    AgentGenerationResult,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentCleanupRequest,
    AgentCleanupResult
)
from .generator import AgentGeneratorAgent
from .executor import GeneratedAgentExecutor
from .model_selector import ModelSelector
from .verifier import TaskVerifier, TaskVerificationRequest
from typing import Any

logger = logging.getLogger(__name__)


class AgentFactory:
    """
    Factory for creating and managing generated agents.
    
    Responsibilities:
    1. Generate agents (via AgentGeneratorAgent)
    2. Create executors for generated agents
    3. Execute agents
    4. Cleanup agents and workspaces
    
    Usage:
        factory = AgentFactory(model_client, runtime)
        
        # Generate agent
        result = await factory.generate_agent(request)
        
        # Execute agent
        exec_result = await factory.execute_agent(agent_id, "Begin task")
        
        # Cleanup
        await factory.cleanup_agent(agent_id)
    """
    
    def __init__(
        self,
        generator_client: ChatCompletionClient,
        executor_clients: Dict[str, ChatCompletionClient],
        verifier_client: ChatCompletionClient,
        runtime: SingleThreadedAgentRuntime,
        base_work_dir: Path = Path("/tmp/agent_workspaces")
    ):
        """
        Initialize Agent Factory.

        Args:
            generator_client: Claude 4.5 client for generating system prompts
            executor_clients: Dict of model clients for generated agents
                             Keys: model names (gpt-4o, gpt-5-low, claude-4.5, etc.)
                             Values: ChatCompletionClient instances
            verifier_client: Client for task verification (typically Claude 4.5)
            runtime: AutoGen runtime
            base_work_dir: Base directory for agent workspaces
        """
        self._generator_client = generator_client
        self._executor_clients = executor_clients
        self._verifier_client = verifier_client
        self._runtime = runtime
        self._base_work_dir = base_work_dir
        self._base_work_dir.mkdir(parents=True, exist_ok=True)

        # Track active agents and their info (executors, system prompts, etc.)
        self._active_agents: Dict[str, Dict[str, Any]] = {}
        self._agent_workspaces: Dict[str, Path] = {}
        self._agent_requests: Dict[str, AgentGenerationRequest] = {}  # Store original requests

        logger.info(f"AgentFactory initialized with work_dir: {base_work_dir}")
        logger.info(f"Available executor models: {list(executor_clients.keys())}")
    
    async def generate_agent(
        self,
        request: AgentGenerationRequest,
        tools: Optional[List] = None
    ) -> AgentGenerationResult:
        """
        Generate a specialized agent.
        
        Sends request to AgentGeneratorAgent (Claude 4.5) which will
        create an appropriate system prompt for the task.
        """
        logger.info(f"Generating agent for request: {request.request_id}")
        
        # Send to Agent Generator
        result = await self._runtime.send_message(
            request,
            recipient=AgentId("agent_generator", "default")
        )
        
        if result.status == "success":
            # Create workspace for this agent
            workspace = self._base_work_dir / result.agent_id
            workspace.mkdir(parents=True, exist_ok=True)
            self._agent_workspaces[result.agent_id] = workspace
            
            # Create code executor
            code_executor = LocalCommandLineCodeExecutor(
                work_dir=str(workspace),
                timeout=request.timeout_seconds
            )
            
            # Get the appropriate model client for this agent
            selected_model = result.selected_model
            if selected_model in self._executor_clients:
                executor_client = self._executor_clients[selected_model]
                logger.info(f"Using {selected_model} client for agent {result.agent_id}")
            else:
                # Fallback to first available client
                fallback_model = list(self._executor_clients.keys())[0]
                executor_client = self._executor_clients[fallback_model]
                logger.warning(
                    f"Model {selected_model} not available, using fallback: {fallback_model}"
                )
            
            # Store executor and agent info for cleanup
            agent_info = {
                "system_prompt": result.system_prompt,
                "code_executor": code_executor,
                "max_iterations": request.max_iterations,
                "selected_model": selected_model,
                "task_complexity": result.task_complexity,
            }
            self._active_agents[result.agent_id] = agent_info
            
            # Store original request for verification later
            self._agent_requests[result.agent_id] = request

            # Register executor with runtime
            # CRITICAL: Lambda must create a NEW instance each time
            # The runtime will call this lambda to instantiate the agent
            # Use default arguments to capture values (not references)
            # Use tools from request if provided, otherwise use parameter
            agent_tools = request.tools if request.tools is not None else tools
            
            await GeneratedAgentExecutor.register(
                self._runtime,
                result.agent_id,
                lambda aid=result.agent_id, sp=result.system_prompt, ce=code_executor, mi=request.max_iterations, mc=executor_client, t=agent_tools: GeneratedAgentExecutor(
                    agent_id=aid,
                    system_prompt=sp,
                    model_client=mc,
                    code_executor=ce,
                    max_iterations=mi,
                    tools=t
                )
            )
            
            logger.info(f"Agent {result.agent_id} created and registered with model {selected_model}")
        
        return result
    
    async def execute_agent(
        self,
        agent_id: str,
        message: str,
        verify: bool = True
    ) -> AgentExecutionResult:
        """
        Execute a generated agent and optionally verify completion.
        
        Args:
            agent_id: ID of the agent to execute
            message: Instruction message
            verify: Whether to run independent verification (default: True)
        """
        if agent_id not in self._active_agents:
            logger.error(f"Agent {agent_id} not found")
            return AgentExecutionResult(
                agent_id=agent_id,
                status="failed",
                output="",
                iterations=0,
                duration_seconds=0.0,
                error=f"Agent {agent_id} not found"
            )
        
        logger.info(f"Executing agent {agent_id}")
        
        request = AgentExecutionRequest(
            agent_id=agent_id,
            message=message
        )
        
        result = await self._runtime.send_message(
            request,
            recipient=AgentId(agent_id, "default")
        )
        
        # If verification is enabled and we have the original request
        if verify and agent_id in self._agent_requests:
            logger.info(f"Verifying task completion for agent {agent_id}")
            original_request = self._agent_requests[agent_id]
            
            # Create verifier workspace
            verifier_workspace = self._base_work_dir / f"{agent_id}_verifier"
            verifier_workspace.mkdir(parents=True, exist_ok=True)
            
            # Create code executor for verifier
            verifier_executor = LocalCommandLineCodeExecutor(
                work_dir=str(verifier_workspace),
                timeout=original_request.timeout_seconds
            )
            
            # Create verifier
            verifier = TaskVerifier(
                model_client=self._verifier_client,
                code_executor=verifier_executor
            )
            
            # Create verification request
            from autogen_core import CancellationToken, MessageContext
            verification_request = TaskVerificationRequest(
                agent_id=agent_id,
                task_description=original_request.task_description,
                goal=original_request.goal,
                context=original_request.context,
                success_criteria=original_request.success_criteria,
                agent_output=result.output
            )
            
            # Verify with a basic cancellation token
            cancellation_token = CancellationToken()
            mock_context = type('MockContext', (), {'cancellation_token': cancellation_token})()
            verification_result = await verifier.verify_task(
                verification_request,
                mock_context
            )
            
            # Update result status based on verification
            if not verification_result.verified:
                logger.warning(f"Verification FAILED for agent {agent_id}")
                logger.warning(f"Details: {verification_result.verification_details}")
                result.status = "failed"
                result.error = f"Verification failed: {verification_result.verification_details}"
                if verification_result.errors_found:
                    result.error += f" | Errors: {', '.join(verification_result.errors_found)}"
            else:
                logger.info(f"Verification PASSED for agent {agent_id}")
                result.status = "completed"
                result.error = None
            
            # Cleanup verifier
            await verifier_executor.stop()
            shutil.rmtree(verifier_workspace, ignore_errors=True)
        
        return result
    
    async def cleanup_agent(self, agent_id: str) -> AgentCleanupResult:
        """
        Cleanup a generated agent and its workspace.
        
        Steps:
        1. Stop code executor
        2. Unregister from runtime
        3. Delete workspace
        4. Remove from tracking
        """
        logger.info(f"Cleaning up agent {agent_id}")
        
        files_removed = 0
        
        try:
            # Get agent info
            agent_info = self._active_agents.get(agent_id)
            if agent_info:
                # Stop code executor
                await agent_info["code_executor"].stop()
                
                # Remove from tracking
                del self._active_agents[agent_id]
            
            # Delete workspace
            workspace = self._agent_workspaces.get(agent_id)
            if workspace and workspace.exists():
                files_removed = len(list(workspace.rglob("*")))
                shutil.rmtree(workspace)
                del self._agent_workspaces[agent_id]
            
            logger.info(
                f"Agent {agent_id} cleaned up ({files_removed} files removed)"
            )
            
            return AgentCleanupResult(
                agent_id=agent_id,
                status="cleaned",
                files_removed=files_removed
            )
            
        except Exception as e:
            logger.error(
                f"Failed to cleanup agent {agent_id}: {e}",
                exc_info=True
            )
            return AgentCleanupResult(
                agent_id=agent_id,
                status="failed",
                files_removed=files_removed,
                error=str(e)
            )
    
    async def cleanup_all(self):
        """Cleanup all active agents"""
        logger.info("Cleaning up all agents")
        
        agent_ids = list(self._active_agents.keys())
        for agent_id in agent_ids:
            await self.cleanup_agent(agent_id)
    
    def get_active_agents(self) -> list[str]:
        """Get list of active agent IDs"""
        return list(self._active_agents.keys())
