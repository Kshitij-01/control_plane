"""
Task Agent Factory - Creates and registers boss-worker agent pairs
Follows AutoGen best practices for agent creation and registration
"""

import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from autogen_core import SingleThreadedAgentRuntime, TypeSubscription
from autogen_core.models import ChatCompletionClient

logger = logging.getLogger(__name__)


class TaskAgentFactory:
    """
    Factory for creating and registering boss-worker agent pairs.
    
    Best Practices:
    1. Use factory functions (lambdas) for agent instantiation
    2. Register agents with runtime before adding subscriptions
    3. Use TypeSubscription for topic-based communication
    4. Keep agent creation modular and reusable
    5. Ensure proper dependency injection
    """
    
    def __init__(self, runtime: SingleThreadedAgentRuntime):
        """
        Initialize the factory with a runtime instance.
        
        Args:
            runtime: The AutoGen runtime that will manage agents
        """
        self.runtime = runtime
        self.registered_agents = {}
        logger.info("TaskAgentFactory initialized")
    
    async def create_boss_worker_pair(
        self,
        run_id: str,
        workspace_path: Path,
        knowledge_systems: Dict[str, Any],
        gpt5_client: ChatCompletionClient,
        claude_client: ChatCompletionClient,
        pair_id: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Create and register a boss-worker agent pair.
        
        Args:
            run_id: Unique identifier for the current run
            workspace_path: Path to the workspace directory (should be phase2 subdirectory)
            knowledge_systems: Dict containing 'catalog' and 'vector_store'
            gpt5_client: Model client for GPT-5 (boss agent)
            claude_client: Model client for Claude 4.5 (worker agent)
            pair_id: Optional identifier for this pair (defaults to run_id)
        
        Returns:
            Tuple of (boss_topic_type, worker_topic_type)
        """
        if pair_id is None:
            pair_id = run_id
        
        # Ensure workspace path exists
        workspace_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using workspace directory: {workspace_path}")
        
        # Define topic types for this pair
        boss_topic_type = f"boss_agent_{pair_id}"
        worker_topic_type = f"worker_agent_{pair_id}"
        orchestrator_topic_type = "orchestrator_topic"
        
        logger.info(f"Creating boss-worker pair for run {run_id} with pair_id {pair_id}")
        
        # Import agent classes (lazy import to avoid circular dependencies)
        from control_plane_v2.phase_2.boss_agent_autonomous import BossAgent
        from control_plane_v2.phase_2.worker_agent_autonomous import WorkerAgent
        
        # Create and register Boss Agent (GPT-5)
        logger.info(f"Registering boss agent: {boss_topic_type}")
        boss_agent_type = await BossAgent.register(
            self.runtime,
            type=boss_topic_type,
            factory=lambda: BossAgent(
                agent_id=f"boss_{pair_id}",
                workspace_path=workspace_path,
                knowledge_systems=knowledge_systems,
                model_client=gpt5_client,
                worker_topic_type=worker_topic_type,
                orchestrator_topic_type=orchestrator_topic_type
            )
        )
        
        # Add subscription for boss agent
        await self.runtime.add_subscription(
            TypeSubscription(
                topic_type=boss_topic_type,
                agent_type=boss_agent_type.type
            )
        )
        
        logger.info(f"Boss agent registered and subscribed to {boss_topic_type}")
        
        # Create and register Worker Agent (Claude 4.5)
        logger.info(f"Registering worker agent: {worker_topic_type}")
        worker_agent_type = await WorkerAgent.register(
            self.runtime,
            type=worker_topic_type,
            factory=lambda: WorkerAgent(
                agent_id=f"worker_{pair_id}",
                workspace_path=workspace_path,
                knowledge_systems=knowledge_systems,
                model_client=claude_client,
                boss_topic_type=boss_topic_type
            )
        )
        
        # Add subscription for worker agent
        await self.runtime.add_subscription(
            TypeSubscription(
                topic_type=worker_topic_type,
                agent_type=worker_agent_type.type
            )
        )
        
        logger.info(f"Worker agent registered and subscribed to {worker_topic_type}")
        
        # Store registration info
        self.registered_agents[pair_id] = {
            "boss_topic": boss_topic_type,
            "worker_topic": worker_topic_type,
            "boss_agent_type": boss_agent_type.type,
            "worker_agent_type": worker_agent_type.type,
            "run_id": run_id,
            "workspace_path": workspace_path
        }
        
        logger.info(f"Boss-worker pair created successfully: {boss_topic_type} <-> {worker_topic_type}")
        
        return boss_topic_type, worker_topic_type
    
    async def create_multiple_pairs(
        self,
        run_id: str,
        workspace_path: Path,
        knowledge_systems: Dict[str, Any],
        gpt5_client: ChatCompletionClient,
        claude_client: ChatCompletionClient,
        num_pairs: int = 1
    ) -> list[Tuple[str, str]]:
        """
        Create multiple boss-worker pairs for parallel task execution.
        
        Args:
            run_id: Unique identifier for the current run
            workspace_path: Path to the workspace directory
            knowledge_systems: Dict containing 'catalog' and 'vector_store'
            gpt5_client: Model client for GPT-5
            claude_client: Model client for Claude 4.5
            num_pairs: Number of pairs to create
        
        Returns:
            List of (boss_topic_type, worker_topic_type) tuples
        """
        logger.info(f"Creating {num_pairs} boss-worker pairs for run {run_id}")
        
        pairs = []
        for i in range(num_pairs):
            pair_id = f"{run_id}_pair_{i}"
            boss_topic, worker_topic = await self.create_boss_worker_pair(
                run_id=run_id,
                workspace_path=workspace_path,
                knowledge_systems=knowledge_systems,
                gpt5_client=gpt5_client,
                claude_client=claude_client,
                pair_id=pair_id
            )
            pairs.append((boss_topic, worker_topic))
        
        logger.info(f"Created {len(pairs)} boss-worker pairs successfully")
        return pairs
    
    def get_pair_info(self, pair_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a registered agent pair.
        
        Args:
            pair_id: Identifier for the pair
        
        Returns:
            Dict with pair information or None if not found
        """
        return self.registered_agents.get(pair_id)
    
    def get_all_pairs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about all registered agent pairs.
        
        Returns:
            Dict mapping pair_id to pair information
        """
        return self.registered_agents.copy()
    
    def get_boss_topic_for_run(self, run_id: str) -> Optional[str]:
        """
        Get the boss topic type for a specific run.
        
        Args:
            run_id: Run identifier
        
        Returns:
            Boss topic type or None if not found
        """
        pair_info = self.registered_agents.get(run_id)
        return pair_info["boss_topic"] if pair_info else None
    
    def get_worker_topic_for_run(self, run_id: str) -> Optional[str]:
        """
        Get the worker topic type for a specific run.
        
        Args:
            run_id: Run identifier
        
        Returns:
            Worker topic type or None if not found
        """
        pair_info = self.registered_agents.get(run_id)
        return pair_info["worker_topic"] if pair_info else None

