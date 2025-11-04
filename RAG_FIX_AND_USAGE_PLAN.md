# 🔧 RAG FIX AND USAGE PLAN

## 🎯 Strategy: **Multi-Layered Approach**

After analyzing the codebase, I recommend a **hybrid approach** combining:
1. **Fix the existing SimpleVectorStore** (Quick fix for Bug #18)
2. **Add RAG as a Worker Tool** (Optional, for advanced queries)
3. **Inject RAG into Boss Planning** (Automatic, for intelligent task planning)

---

## 📊 CURRENT STATE ANALYSIS

### What Exists:

1. **RAG Infrastructure ✅**
   - `RAGInjector` class (writes to RAG)
   - `SimpleVectorStore` class (storage)
   - `AzureOpenAIRAGMemory` class (Azure-backed)
   - `KnowledgeSystem` class (unified interface)

2. **Boss Integration (PARTIAL) ⚠️**
   - Boss has `self.rag_injector`
   - Boss WRITES to RAG after task completion
   - Boss does NOT READ from RAG during planning ❌

3. **Worker Integration (NONE) ❌**
   - Worker has NO access to RAG
   - Worker cannot query past learnings
   - Worker cannot search for solutions

### Critical Bug (#18):

```python
# Line 77 in rag_injector.py
self.vector_store.add_document(  # ❌ Method doesn't exist!
    content=chunk['content'],
    metadata={...}
)
```

**Error:**
```
'SimpleVectorStore' object has no attribute 'add_document'
```

**Root Cause:**
- `SimpleVectorStore` has method `add()` not `add_document()`
- Method name mismatch between `RAGInjector` and `SimpleVectorStore`

---

## 🔧 FIX PLAN

### **Phase 1: Fix SimpleVectorStore (CRITICAL - 30 min)**

#### Fix #1: Add `add_document()` method wrapper

**File:** `control_plane_v2/phase_2/orchestrator_phase2_v2.py`

**Location:** SimpleVectorStore class

**Change:**
```python
class SimpleVectorStore:
    """Simple vector store using NumPy and cosine similarity"""
    
    # ... existing methods ...
    
    def add_document(self, content: str, metadata: dict = None):
        """
        Add document with metadata (compatible with RAGInjector).
        
        This is a wrapper around add() to match the API expected by RAGInjector.
        
        Args:
            content: Text content to embed and store
            metadata: Optional metadata dict (task_id, filename, etc.)
        """
        # Use the existing add() method
        return self.add(
            text=content,
            metadata=metadata or {}
        )
```

**Impact:** Fixes Bug #18, enables RAG injection ✅

---

### **Phase 2: Enable RAG Retrieval in Boss (HIGH - 1 hour)**

#### Fix #2: Boss queries RAG during planning

**File:** `control_plane_v2/phase_2/boss_agent_autonomous.py`

**Location:** `_plan_subtasks()` method (line ~492)

**Current Code:**
```python
async def _plan_subtasks(self, task_message: TaskMessage) -> List[Dict]:
    """Use GPT-5 to plan subtasks"""
    
    # Check file catalog
    catalog_result = await self.tools.access_catalog("list")
    
    # Extract work_scope
    work_scope_info = ...
    
    # Generate plan
    prompt = f"""Task: {task_message.task_description}
    Input Files: {task_message.input_files}
    {catalog_info}
    {work_scope_info}
    ...
    """
```

**Enhanced Code:**
```python
async def _plan_subtasks(self, task_message: TaskMessage) -> List[Dict]:
    """Use GPT-5 to plan subtasks with RAG-enhanced context"""
    
    # Check file catalog (existing)
    catalog_result = await self.tools.access_catalog("list")
    
    # NEW: Query RAG for relevant past learnings
    rag_context = ""
    if hasattr(self, 'vector_store') and self.vector_store:
        try:
            # Search for similar tasks
            from control_plane_v2.phase_2.orchestrator_phase2_v2 import get_openai_embedding
            
            # Create query from task description
            query = f"{task_message.task_description} {task_message.task_type}"
            query_embedding = await get_openai_embedding(query)
            
            # Search vector store
            results = self.vector_store.search(query_embedding, top_k=3)
            
            if results:
                rag_context = "\n\nRELEVANT PAST LEARNINGS (RAG):\n"
                rag_context += "="*60 + "\n"
                rag_context += "The system has solved similar tasks before. Use these learnings:\n\n"
                
                for i, result in enumerate(results, 1):
                    similarity = result.get('similarity', 0)
                    text = result.get('text', '')
                    metadata = result.get('metadata', {})
                    task_id = metadata.get('task_id', 'unknown')
                    
                    rag_context += f"Learning {i} (similarity: {similarity:.2f}):\n"
                    rag_context += f"  From task: {task_id}\n"
                    rag_context += f"  Content: {text[:500]}...\n\n"
                
                logger.info(f"[RAG] Found {len(results)} relevant past learnings")
            else:
                logger.info(f"[RAG] No relevant past learnings found (this may be a new task type)")
        except Exception as e:
            logger.warning(f"[RAG] Failed to query: {e}")
    
    # Generate plan with RAG context
    prompt = f"""Task: {task_message.task_description}
    Input Files: {task_message.input_files}
    {catalog_info}
    {work_scope_info}
    {rag_context}  # NEW: Include RAG context
    ...
    """
```

**Impact:**
- Boss uses past task knowledge for planning ✅
- Better task decomposition ✅
- Avoids repeating mistakes ✅

---

### **Phase 3: Add RAG as Worker Tool (OPTIONAL - 2 hours)**

#### Option A: Add `query_rag` Tool to TaskAgentTools

**File:** `control_plane_v2/phase_2/task_agent_tools.py`

**Add New Method:**
```python
async def query_rag(
    self,
    query: str,
    top_k: int = 3,
    task_filter: str = None
) -> Dict[str, Any]:
    """
    Query RAG system for relevant past learnings.
    
    Args:
        query: Search query (natural language)
        top_k: Number of results to return
        task_filter: Optional task_id to filter results
        
    Returns:
        {
            "success": bool,
            "results": [
                {
                    "text": str,
                    "similarity": float,
                    "metadata": dict
                }
            ]
        }
    """
    try:
        if not self.vector_store:
            return {
                "success": False,
                "error": "RAG system not available",
                "results": []
            }
        
        # Get embedding for query
        from control_plane_v2.phase_2.orchestrator_phase2_v2 import get_openai_embedding
        query_embedding = await get_openai_embedding(query)
        
        # Search vector store
        results = self.vector_store.search(query_embedding, top_k=top_k)
        
        # Filter by task if specified
        if task_filter:
            results = [r for r in results if r.get('metadata', {}).get('task_id') == task_filter]
        
        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        logger.error(f"[RAG_QUERY] Failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "results": []
        }
```

#### Option B: Give Worker Direct Access (Simpler)

**File:** `control_plane_v2/phase_2/worker_agent_autonomous.py`

**Update System Prompt:**
```python
self.system_prompt = SystemMessage(
    content="""You are Claude 4.5, an autonomous problem solver.

=== TOOLS AVAILABLE ===

1. todo_write_function - Manage TODO list
2. scan_directory - Explore workspace
3. query_rag - Search past task learnings  # NEW!

QUERY_RAG USAGE:
- Search for solutions to similar problems you've solved before
- Example: query_rag("How to parse multi-line table cells in PDF")
- Returns: Past learnings with similarity scores
- Use this BEFORE writing code for complex tasks

...
"""
)
```

**Add RAG Query Method:**
```python
async def _query_rag(self, query: str, top_k: int = 3) -> List[Dict]:
    """Query RAG for relevant learnings"""
    if not hasattr(self, 'vector_store') or not self.vector_store:
        logger.warning("[RAG] Vector store not available")
        return []
    
    try:
        from control_plane_v2.phase_2.orchestrator_phase2_v2 import get_openai_embedding
        query_embedding = await get_openai_embedding(query)
        results = self.vector_store.search(query_embedding, top_k=top_k)
        return results
    except Exception as e:
        logger.error(f"[RAG] Query failed: {e}")
        return []
```

**Pros of Option A (Tool):**
- ✅ Worker can explicitly query RAG
- ✅ Clean tool-based interface
- ✅ Worker controls when to use RAG

**Pros of Option B (Direct Access):**
- ✅ Simpler implementation
- ✅ No new tool registration needed
- ✅ Worker can call directly

**Cons of Both:**
- ⚠️ Adds complexity to Worker workflow
- ⚠️ Worker may not use it effectively
- ⚠️ May slow down execution (extra queries)

**Recommendation:** Start WITHOUT Worker RAG access, only add if needed

---

## 🎯 RECOMMENDED IMPLEMENTATION PLAN

### **Stage 1: Fix Critical Bug (IMMEDIATE)**

1. ✅ Add `add_document()` wrapper to `SimpleVectorStore`
2. ✅ Test RAG injection works
3. ✅ Verify no more "add_document" errors

**Time:** 30 minutes  
**Priority:** 🔴 CRITICAL  
**Impact:** Enables RAG system

---

### **Stage 2: Enable Boss RAG Retrieval (HIGH PRIORITY)**

1. ✅ Add RAG query to `_plan_subtasks()`
2. ✅ Include RAG context in planning prompt
3. ✅ Log RAG usage for monitoring

**Time:** 1 hour  
**Priority:** 🟠 HIGH  
**Impact:** Intelligent task planning

---

### **Stage 3: Worker RAG Tool (OPTIONAL - IF NEEDED)**

1. ⚠️ Monitor Boss RAG effectiveness
2. ⚠️ If needed, add `query_rag` tool
3. ⚠️ Update Worker prompt with RAG usage examples

**Time:** 2 hours  
**Priority:** 🟡 MEDIUM  
**Impact:** Worker can search past solutions

---

## 📊 COMPARISON: Tool vs Automatic

### **Approach 1: RAG as Worker Tool**

**How it works:**
```python
# Worker explicitly calls RAG tool
Worker: "I need to parse PDFs with multi-line cells"
Worker calls: query_rag("parse multi-line PDF table cells")
RAG returns: "Previous task used pdfplumber with row-span detection..."
Worker: "I'll use that approach!"
```

**Pros:**
- ✅ Worker has full control
- ✅ Only queries when needed
- ✅ Can search for specific solutions

**Cons:**
- ❌ Worker may forget to use it
- ❌ Extra attempt spent querying
- ❌ Adds complexity to workflow

---

### **Approach 2: Automatic RAG Injection (RECOMMENDED)**

**How it works:**
```python
# Boss automatically includes RAG context
Boss: "Planning subtasks for PDF extraction..."
Boss queries RAG: "extract PDF data template-based"
RAG returns: "Task develop_template_type_a used this approach..."
Boss includes in prompt: "Based on past learnings, consider..."
Worker receives enhanced prompt with context
```

**Pros:**
- ✅ Automatic - no Worker action needed
- ✅ Every task gets relevant context
- ✅ Simpler Worker workflow
- ✅ Boss makes intelligent decisions

**Cons:**
- ⚠️ Worker can't query on-demand
- ⚠️ Boss must choose relevant context

---

## 🎯 FINAL RECOMMENDATION

### **Hybrid Approach:**

1. **Fix SimpleVectorStore** (30 min) - CRITICAL
   - Add `add_document()` method
   - Enable RAG injection

2. **Boss Auto-RAG** (1 hour) - HIGH PRIORITY
   - Boss queries RAG during planning
   - Includes relevant learnings in subtask prompts
   - Automatic, no Worker changes needed

3. **Worker RAG Tool** (2 hours) - ONLY IF NEEDED
   - Monitor Boss RAG effectiveness first
   - Add tool if Workers need on-demand search
   - Start without it, add later if valuable

### **Why This Approach:**

✅ **Automatic First:** Boss RAG gives immediate value without Worker changes  
✅ **Simple:** Worker workflow stays clean  
✅ **Scalable:** Can add Worker tool later if needed  
✅ **Effective:** Boss has better context for planning  

---

## 🔧 IMPLEMENTATION STEPS

### **Step 1: Fix SimpleVectorStore (Now)**

```python
# File: control_plane_v2/phase_2/orchestrator_phase2_v2.py
# Add after existing add() method

def add_document(self, content: str, metadata: dict = None):
    """Add document (wrapper for RAGInjector compatibility)"""
    return self.add(text=content, metadata=metadata or {})
```

### **Step 2: Enable Boss RAG (Next)**

```python
# File: control_plane_v2/phase_2/boss_agent_autonomous.py
# In _plan_subtasks() method

# Query RAG for similar tasks
rag_context = ""
if hasattr(self, 'vector_store') and self.vector_store:
    query = f"{task_message.task_description} {task_message.task_type}"
    query_embedding = await get_openai_embedding(query)
    results = self.vector_store.search(query_embedding, top_k=3)
    
    if results:
        rag_context = format_rag_context(results)  # Helper function

# Include in planning prompt
prompt = f"""...
{rag_context}
..."""
```

### **Step 3: Monitor & Iterate**

- Track RAG usage in logs
- Measure task planning quality
- Add Worker tool only if needed

---

## ✅ SUCCESS METRICS

After implementation, we should see:

1. **No RAG Injection Errors** ✅
   - Zero `'add_document' not found` errors
   - Successful injection of task outputs

2. **Boss Uses RAG** ✅
   - Logs show RAG queries during planning
   - Planning prompts include past learnings

3. **Better Task Planning** ✅
   - Boss creates more efficient subtask plans
   - Fewer retries due to better upfront planning
   - Reuses successful patterns from past tasks

4. **Knowledge Accumulation** ✅
   - Vector store grows with each task
   - Similar tasks benefit from past learnings
   - System gets smarter over time

---

## 🎯 DECISION: START WITH AUTOMATIC BOSS RAG

**Recommendation:** Don't give RAG as tool to Worker initially

**Rationale:**
1. Boss has better context for planning
2. Simpler Worker workflow
3. Can add Worker tool later if needed
4. Automatic = guaranteed to be used

**Next Actions:**
1. Fix SimpleVectorStore (30 min)
2. Add Boss RAG query (1 hour)
3. Test with Halliburton task
4. Monitor effectiveness
5. Iterate based on results

---

**Status:** READY TO IMPLEMENT  
**Priority:** 🔴 CRITICAL (Bug #18) + 🟠 HIGH (Feature)  
**Effort:** 1.5 hours total  
**Impact:** Enables knowledge reuse, better planning

