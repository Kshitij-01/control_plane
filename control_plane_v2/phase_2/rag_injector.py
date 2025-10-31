"""
RAG Injector - Converts task outputs (JSON files) into embeddings and injects into vector store
Allows agents to semantically query previous task artifacts
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class RAGInjector:
    """
    Injects task artifacts (JSON files) into RAG system for semantic retrieval
    """
    
    def __init__(self, vector_store: Any):
        """
        Initialize RAG injector
        
        Args:
            vector_store: Vector store for storing embeddings
        """
        self.vector_store = vector_store
        logger.info("RAG Injector initialized")
    
    def inject_task_outputs(
        self, 
        task_id: str, 
        output_files: List[Dict[str, str]],
        task_description: str = ""
    ) -> int:
        """
        Inject task output files into RAG system
        
        Args:
            task_id: ID of the task that created these files
            output_files: List of dicts with 'filename' and 'absolute_path'
            task_description: Description of what the task did
            
        Returns:
            Number of documents injected
        """
        injected_count = 0
        
        for file_info in output_files:
            filename = file_info.get('filename', '')
            absolute_path = file_info.get('absolute_path', '')
            
            # Only process JSON files
            if not filename.endswith('.json'):
                logger.debug(f"Skipping non-JSON file: {filename}")
                continue
            
            try:
                # Read JSON file
                file_path = Path(absolute_path)
                if not file_path.exists():
                    logger.warning(f"File not found: {absolute_path}")
                    continue
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Convert JSON to text chunks for embedding
                chunks = self._json_to_chunks(
                    data=data,
                    filename=filename,
                    task_id=task_id,
                    task_description=task_description
                )
                
                # Inject chunks into vector store
                for chunk in chunks:
                    self.vector_store.add_document(
                        content=chunk['content'],
                        metadata={
                            'task_id': task_id,
                            'filename': filename,
                            'file_path': absolute_path,
                            'chunk_type': chunk['type'],
                            'task_description': task_description
                        }
                    )
                    injected_count += 1
                
                logger.info(f"Injected {len(chunks)} chunks from {filename} into RAG")
                
            except Exception as e:
                logger.error(f"Failed to inject {filename}: {e}")
                continue
        
        logger.info(f"Total documents injected: {injected_count}")
        return injected_count
    
    def _json_to_chunks(
        self, 
        data: Any, 
        filename: str, 
        task_id: str,
        task_description: str
    ) -> List[Dict[str, str]]:
        """
        Convert JSON data to text chunks suitable for embedding
        
        Args:
            data: JSON data (dict, list, or primitive)
            filename: Name of the source file
            task_id: ID of the task that created this file
            task_description: Description of the task
            
        Returns:
            List of chunks with 'content' and 'type'
        """
        chunks = []
        
        # Add overview chunk
        overview = self._create_overview_chunk(data, filename, task_id, task_description)
        if overview:
            chunks.append(overview)
        
        # Handle different JSON structures
        if isinstance(data, dict):
            chunks.extend(self._chunk_dict(data, filename, task_id))
        elif isinstance(data, list):
            chunks.extend(self._chunk_list(data, filename, task_id))
        else:
            # Simple value - just add as single chunk
            chunks.append({
                'content': f"File: {filename}\nTask: {task_id}\nValue: {str(data)}",
                'type': 'value'
            })
        
        return chunks
    
    def _create_overview_chunk(
        self, 
        data: Any, 
        filename: str, 
        task_id: str,
        task_description: str
    ) -> Optional[Dict[str, str]]:
        """Create an overview chunk describing the file"""
        try:
            content_parts = [
                f"File: {filename}",
                f"Task: {task_id}",
                f"Description: {task_description}" if task_description else None
            ]
            
            if isinstance(data, dict):
                content_parts.append(f"Type: Dictionary with {len(data)} keys")
                content_parts.append(f"Keys: {', '.join(list(data.keys())[:20])}")
            elif isinstance(data, list):
                content_parts.append(f"Type: List with {len(data)} items")
                if data and isinstance(data[0], dict):
                    content_parts.append(f"Item keys: {', '.join(list(data[0].keys())[:10])}")
            
            content = "\n".join([p for p in content_parts if p])
            
            return {
                'content': content,
                'type': 'overview'
            }
        except Exception as e:
            logger.warning(f"Failed to create overview chunk: {e}")
            return None
    
    def _chunk_dict(self, data: dict, filename: str, task_id: str) -> List[Dict[str, str]]:
        """Chunk a dictionary into semantic pieces"""
        chunks = []
        
        # Special handling for schema files
        if 'schema' in filename.lower() or isinstance(data, list):
            # Schema is often a list of column definitions
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        chunk_content = self._format_dict_item(item, filename, task_id)
                        chunks.append({
                            'content': chunk_content,
                            'type': 'schema_column'
                        })
            else:
                # Dict-based schema
                for key, value in data.items():
                    chunk_content = f"File: {filename}\nTask: {task_id}\nKey: {key}\n"
                    chunk_content += f"Value: {json.dumps(value, indent=2)}"
                    chunks.append({
                        'content': chunk_content,
                        'type': 'schema_field'
                    })
        
        # Special handling for stats/marginals files
        elif 'stats' in filename.lower() or 'marginal' in filename.lower():
            for key, value in data.items():
                chunk_content = f"File: {filename}\nTask: {task_id}\nColumn: {key}\n"
                chunk_content += f"Statistics: {json.dumps(value, indent=2)}"
                chunks.append({
                    'content': chunk_content,
                    'type': 'column_stats'
                })
        
        # Special handling for correlation files
        elif 'correlation' in filename.lower():
            for corr_type, matrix in data.items():
                chunk_content = f"File: {filename}\nTask: {task_id}\n"
                chunk_content += f"Correlation Type: {corr_type}\n"
                chunk_content += f"Matrix: {json.dumps(matrix, indent=2)}"
                chunks.append({
                    'content': chunk_content,
                    'type': 'correlation_matrix'
                })
        
        # Generic dict handling
        else:
            for key, value in data.items():
                chunk_content = f"File: {filename}\nTask: {task_id}\nKey: {key}\n"
                chunk_content += f"Value: {json.dumps(value, indent=2)[:1000]}"  # Limit size
                chunks.append({
                    'content': chunk_content,
                    'type': 'key_value'
                })
        
        return chunks
    
    def _chunk_list(self, data: list, filename: str, task_id: str) -> List[Dict[str, str]]:
        """Chunk a list into semantic pieces"""
        chunks = []
        
        # If list of dicts (common for schemas), chunk each item
        if data and isinstance(data[0], dict):
            for i, item in enumerate(data):
                chunk_content = self._format_dict_item(item, filename, task_id)
                chunks.append({
                    'content': chunk_content,
                    'type': 'list_item'
                })
        else:
            # Simple list - chunk in groups
            chunk_size = 50
            for i in range(0, len(data), chunk_size):
                chunk_data = data[i:i+chunk_size]
                chunk_content = f"File: {filename}\nTask: {task_id}\n"
                chunk_content += f"Items {i} to {i+len(chunk_data)}:\n"
                chunk_content += json.dumps(chunk_data, indent=2)
                chunks.append({
                    'content': chunk_content,
                    'type': 'list_chunk'
                })
        
        return chunks
    
    def _format_dict_item(self, item: dict, filename: str, task_id: str) -> str:
        """Format a dictionary item as a readable chunk"""
        content = f"File: {filename}\nTask: {task_id}\n"
        
        # Add a title if there's a 'name' field
        if 'name' in item:
            content += f"Name: {item['name']}\n"
        
        # Add all fields
        for key, value in item.items():
            if key == 'name':
                continue  # Already added
            
            # Format value based on type
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, indent=2)[:500]  # Limit size
            else:
                value_str = str(value)
            
            content += f"{key}: {value_str}\n"
        
        return content
    
    def query_task_artifacts(
        self, 
        query: str, 
        task_id: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Query task artifacts using semantic search
        
        Args:
            query: Natural language query
            task_id: Optional task ID to filter results
            top_k: Number of results to return
            
        Returns:
            List of relevant chunks with metadata
        """
        try:
            # Query vector store
            results = self.vector_store.query(
                query=query,
                top_k=top_k,
                filter_metadata={'task_id': task_id} if task_id else None
            )
            
            return results
        except Exception as e:
            logger.error(f"Failed to query task artifacts: {e}")
            return []

