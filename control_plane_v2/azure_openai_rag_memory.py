"""
Azure OpenAI RAG Memory - Production Implementation
Uses Azure OpenAI embeddings for semantic search over task learnings
"""
import json
import logging
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
from openai import AzureOpenAI

logger = logging.getLogger(__name__)


class AzureOpenAIRAGMemory:
    """
    RAG Memory using Azure OpenAI Embeddings
    Stores task learnings and enables semantic search
    """
    
    def __init__(
        self,
        workspace_root: str,
        azure_endpoint: str,
        api_key: str,
        api_version: str,
        deployment_name: str = "text-embedding-3-small"
    ):
        """
        Initialize Azure OpenAI RAG Memory
        
        Args:
            workspace_root: Root directory for storage
            azure_endpoint: Azure OpenAI endpoint URL
            api_key: Azure OpenAI API key
            api_version: API version
            deployment_name: Embedding model deployment name
        """
        self._workspace = Path(workspace_root)
        self._storage_path = self._workspace / "azure_rag_memory.pkl"
        self._deployment_name = deployment_name
        
        # Initialize Azure OpenAI client with timeout
        try:
            import httpx
            # Create client with timeout to prevent hanging
            http_client = httpx.Client(timeout=10.0)  # 10 second timeout
            
            self._client = AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=api_key,
                api_version=api_version,
                http_client=http_client
            )
            logger.info(f"[RAG] Azure OpenAI client initialized")
            logger.info(f"[RAG]   Endpoint: {azure_endpoint}")
            logger.info(f"[RAG]   Deployment: {deployment_name}")
        except Exception as e:
            logger.error(f"[RAG] Failed to initialize Azure OpenAI client: {e}")
            raise
        
        # In-memory storage
        self._documents: List[str] = []
        self._embeddings: List[List[float]] = []
        self._metadata: List[Dict[str, Any]] = []
        
        # Load existing data
        self._load_from_disk()
        
        logger.info(f"[RAG] Loaded {len(self._documents)} existing learnings")
    
    def add_learning(
        self,
        text: str,
        task_id: str,
        task_type: str,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add a task learning to the memory
        
        Args:
            text: Learning text (should be descriptive)
            task_id: Task identifier
            task_type: Type of task (extract, transform, merge, load, validation)
            success: Whether the task succeeded
            metadata: Additional metadata
            
        Returns:
            True if added successfully
        """
        try:
            # Generate embedding via Azure OpenAI
            response = self._client.embeddings.create(
                input=text,
                model=self._deployment_name
            )
            
            embedding = response.data[0].embedding
            
            # Prepare metadata
            meta = {
                "task_id": task_id,
                "task_type": task_type,
                "success": success
            }
            if metadata:
                meta.update(metadata)
            
            # Store
            self._documents.append(text)
            self._embeddings.append(embedding)
            self._metadata.append(meta)
            
            # Persist
            self._save_to_disk()
            
            logger.info(f"[RAG] Added learning for {task_id} (total: {len(self._documents)})")
            return True
            
        except Exception as e:
            logger.error(f"[RAG] Failed to add learning: {e}")
            return False
    
    def search(
        self,
        query: str,
        task_type: Optional[str] = None,
        success_only: bool = True,
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant learnings using semantic similarity
        
        Args:
            query: Search query
            task_type: Filter by task type (extract, transform, merge, load, validation)
            success_only: Only return successful task learnings
            top_k: Number of results to return
            
        Returns:
            List of relevant learnings with metadata and similarity scores
        """
        if not self._documents:
            logger.info("[RAG] No learnings in memory yet")
            return []
        
        try:
            # Generate query embedding
            response = self._client.embeddings.create(
                input=query,
                model=self._deployment_name
            )
            query_embedding = response.data[0].embedding
            
            # Calculate similarities with filtering
            results = []
            for i, doc_emb in enumerate(self._embeddings):
                meta = self._metadata[i]
                
                # Apply metadata filters
                if task_type and meta.get('task_type') != task_type:
                    continue
                if success_only and not meta.get('success', False):
                    continue
                
                # Cosine similarity
                similarity = self._cosine_similarity(query_embedding, doc_emb)
                
                results.append({
                    'document': self._documents[i],
                    'metadata': meta,
                    'similarity': float(similarity)
                })
            
            # Sort by similarity (highest first)
            results.sort(key=lambda x: x['similarity'], reverse=True)
            
            # Return top-k
            top_results = results[:top_k]
            
            logger.info(f"[RAG] Search for '{query[:50]}...' returned {len(top_results)} results")
            if top_results:
                logger.info(f"[RAG]   Top similarity: {top_results[0]['similarity']:.3f}")
            
            return top_results
            
        except Exception as e:
            logger.error(f"[RAG] Search failed: {e}")
            return []
    
    def get_context_for_task(
        self,
        task_description: str,
        task_type: str,
        dependencies: List[str]
    ) -> Dict[str, Any]:
        """
        Get relevant context for a task (used by KnowledgeSystem)
        
        Args:
            task_description: Description of the task
            task_type: Type of task
            dependencies: List of dependency task IDs
            
        Returns:
            Dictionary with similar_tasks and relevant_practices
        """
        # Search for similar tasks
        similar = self.search(
            query=task_description,
            task_type=task_type,
            success_only=True,
            top_k=3
        )
        
        # Search for best practices (general search)
        practices = self.search(
            query=f"{task_type} best practices common issues",
            success_only=True,
            top_k=2
        )
        
        return {
            "similar_tasks": [
                {
                    "task_id": item["metadata"]["task_id"],
                    "similarity": item["similarity"],
                    "learnings": {"description": item["document"]},
                    "metadata": item["metadata"]
                }
                for item in similar
            ],
            "relevant_practices": [
                {
                    "description": item["document"],
                    "relevance": item["similarity"]
                }
                for item in practices
            ]
        }
    
    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        a_np = np.array(a)
        b_np = np.array(b)
        return np.dot(a_np, b_np) / (np.linalg.norm(a_np) * np.linalg.norm(b_np))
    
    def _save_to_disk(self):
        """Persist memory to disk"""
        try:
            data = {
                'documents': self._documents,
                'embeddings': self._embeddings,
                'metadata': self._metadata
            }
            
            with open(self._storage_path, 'wb') as f:
                pickle.dump(data, f)
            
            logger.debug(f"[RAG] Saved {len(self._documents)} learnings to disk")
        except Exception as e:
            logger.error(f"[RAG] Failed to save to disk: {e}")
    
    def _load_from_disk(self):
        """Load memory from disk"""
        if not self._storage_path.exists():
            logger.info("[RAG] No existing memory file found (first run)")
            return
        
        try:
            with open(self._storage_path, 'rb') as f:
                data = pickle.load(f)
            
            self._documents = data.get('documents', [])
            self._embeddings = data.get('embeddings', [])
            self._metadata = data.get('metadata', [])
            
            logger.info(f"[RAG] Loaded {len(self._documents)} learnings from disk")
        except Exception as e:
            logger.error(f"[RAG] Failed to load from disk: {e}")
            # Start fresh if load fails
            self._documents = []
            self._embeddings = []
            self._metadata = []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics"""
        task_types = {}
        for meta in self._metadata:
            task_type = meta.get('task_type', 'unknown')
            task_types[task_type] = task_types.get(task_type, 0) + 1
        
        return {
            'total_learnings': len(self._documents),
            'by_task_type': task_types,
            'embedding_dimension': len(self._embeddings[0]) if self._embeddings else 0
        }

