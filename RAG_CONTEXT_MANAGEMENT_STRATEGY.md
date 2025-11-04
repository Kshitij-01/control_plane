# 🎯 RAG CONTEXT MANAGEMENT STRATEGY

## ⚠️ THE PROBLEM YOU IDENTIFIED

### **Concern 1: Context Window Bloat**
- RAG could inject 1000s of tokens into every prompt
- Boss already has: manifest, catalog, work_scope, credentials, etc.
- Adding RAG might exceed GPT-5 context limits
- Wastes tokens on irrelevant information

### **Concern 2: Relevance & Noise**
- Not all RAG results are useful
- Past learnings might be from different task types
- Low-similarity results add noise
- Need to filter for ONLY highly relevant information

---

## 🎯 SOLUTION: SMART RAG WITH STRICT FILTERS

### **Strategy: Multi-Layer Filtering + Token Budgets**

```
┌─────────────────────────────────────────────┐
│  STAGE 1: Query RAG (Retrieve)             │
│  • Semantic search with task description    │
│  • Get top 10 candidates                    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  STAGE 2: Filter by Similarity (Relevance) │
│  • Keep ONLY results with similarity > 0.7  │
│  • Drop low-relevance results               │
│  • Typical: 10 → 2-3 results                │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  STAGE 3: Filter by Task Type (Context)    │
│  • Match task types (extract vs transform)  │
│  • Match file types (PDF vs CSV)            │
│  • Typical: 2-3 → 1-2 results               │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  STAGE 4: Truncate by Token Budget         │
│  • Max 500 tokens for RAG context          │
│  • Summarize if needed                      │
│  • Typical: 200-400 tokens                  │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  STAGE 5: Inject into Prompt               │
│  • Clean, relevant, budget-compliant        │
└─────────────────────────────────────────────┘
```

---

## 🔧 IMPLEMENTATION DETAILS

### **1. Similarity Threshold (Reject Irrelevant)**

```python
# Boss's _plan_subtasks() method

async def _query_rag_smart(
    self, 
    task_description: str, 
    task_type: str,
    min_similarity: float = 0.7  # CRITICAL: Only highly relevant results
) -> str:
    """
    Query RAG with smart filtering to avoid context bloat.
    
    Returns:
        Concise RAG context string (max 500 tokens)
    """
    try:
        if not hasattr(self, 'vector_store') or not self.vector_store:
            return ""
        
        # Get embedding for query
        query = f"{task_description} {task_type}"
        query_embedding = await get_openai_embedding(query)
        
        # Search with more candidates initially
        raw_results = self.vector_store.search(query_embedding, top_k=10)
        
        # FILTER 1: Similarity threshold (reject low-relevance)
        filtered_results = [
            r for r in raw_results 
            if r.get('similarity', 0) >= min_similarity  # ONLY high similarity
        ]
        
        if not filtered_results:
            logger.info(f"[RAG] No high-relevance results (min_sim={min_similarity})")
            return ""  # Return empty instead of noise
        
        logger.info(f"[RAG] Filtered {len(raw_results)} → {len(filtered_results)} results (similarity >= {min_similarity})")
        
        # FILTER 2: Task type matching (only similar task types)
        task_matched = []
        for r in filtered_results:
            metadata = r.get('metadata', {})
            past_task_id = metadata.get('task_id', '')
            
            # Check if task types match (e.g., both are "extract" or "transform")
            if self._is_similar_task_type(task_type, past_task_id):
                task_matched.append(r)
        
        if not task_matched:
            logger.info(f"[RAG] No task-type matches")
            return ""
        
        logger.info(f"[RAG] Task-type filtered {len(filtered_results)} → {len(task_matched)} results")
        
        # FILTER 3: Token budget (limit context size)
        rag_context = self._format_rag_context(
            task_matched[:3],  # Max 3 results
            max_tokens=500     # HARD LIMIT
        )
        
        return rag_context
        
    except Exception as e:
        logger.warning(f"[RAG] Query failed: {e}")
        return ""  # Fail gracefully - continue without RAG
```

---

### **2. Task Type Matching (Contextual Relevance)**

```python
def _is_similar_task_type(self, current_task_type: str, past_task_id: str) -> bool:
    """
    Check if past task is similar to current task.
    
    Examples:
        - "extract" matches "extract_*"
        - "transform" matches "transform_*"
        - "develop_template" matches "develop_template_*"
    """
    # Extract base task type
    current_base = current_task_type.split('_')[0].lower()
    past_base = past_task_id.split('_')[0].lower()
    
    # Exact match
    if current_base == past_base:
        return True
    
    # Synonym matching
    synonyms = {
        'extract': ['parse', 'read', 'load', 'unpack'],
        'transform': ['process', 'convert', 'map', 'aggregate'],
        'analyze': ['examine', 'inspect', 'verify', 'check'],
        'generate': ['create', 'build', 'develop', 'produce']
    }
    
    for category, terms in synonyms.items():
        if current_base in terms and past_base in terms:
            return True
    
    return False
```

---

### **3. Token Budget Enforcement (Hard Limit)**

```python
def _format_rag_context(
    self, 
    results: List[Dict], 
    max_tokens: int = 500
) -> str:
    """
    Format RAG results with strict token budget.
    
    Strategy:
    - If results fit in budget: return all
    - If too long: truncate + summarize
    - Prioritize by similarity score
    """
    if not results:
        return ""
    
    # Build context incrementally, respecting budget
    context_parts = []
    context_parts.append("\n" + "="*60)
    context_parts.append("RELEVANT PAST LEARNINGS (RAG)")
    context_parts.append("="*60)
    context_parts.append("The system solved similar tasks before. Key insights:\n")
    
    current_tokens = self._estimate_tokens(" ".join(context_parts))
    
    for i, result in enumerate(results, 1):
        similarity = result.get('similarity', 0)
        text = result.get('text', '')
        metadata = result.get('metadata', {})
        task_id = metadata.get('task_id', 'unknown')
        chunk_type = metadata.get('chunk_type', 'learning')
        
        # Format this result
        result_text = f"\nLearning #{i} (confidence: {similarity:.0%}):\n"
        result_text += f"  Source: {task_id} ({chunk_type})\n"
        
        # Estimate tokens and truncate if needed
        available_tokens = max_tokens - current_tokens - 50  # Reserve 50 for safety
        text_budget = available_tokens - self._estimate_tokens(result_text)
        
        if text_budget > 100:  # Only include if meaningful space left
            # Truncate text to fit budget
            truncated_text = self._truncate_to_tokens(text, text_budget)
            result_text += f"  Content: {truncated_text}\n"
            
            # Add to context
            context_parts.append(result_text)
            current_tokens = self._estimate_tokens(" ".join(context_parts))
        else:
            # Out of budget - stop adding results
            logger.info(f"[RAG] Token budget exhausted after {i-1} results")
            break
    
    context_parts.append("\nUse these learnings to inform your plan.\n")
    context_parts.append("="*60)
    
    final_context = "\n".join(context_parts)
    final_tokens = self._estimate_tokens(final_context)
    
    logger.info(f"[RAG] Generated context: {final_tokens} tokens from {len(results)} results")
    
    return final_context

def _estimate_tokens(self, text: str) -> int:
    """Rough token estimation (1 token ≈ 4 chars)"""
    return len(text) // 4

def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
    """Truncate text to approximate token count"""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    
    # Truncate and add ellipsis
    truncated = text[:max_chars-3] + "..."
    return truncated
```

---

### **4. Smart Query Construction (Better Retrieval)**

```python
def _build_rag_query(
    self, 
    task_description: str, 
    task_type: str,
    input_files: List[str] = None
) -> str:
    """
    Build intelligent RAG query that captures task essence.
    
    Strategy:
    - Include task description (what to do)
    - Include task type (how it's categorized)
    - Include file types (context)
    - Exclude noise words
    """
    query_parts = []
    
    # Core task
    query_parts.append(task_description)
    
    # Task type
    query_parts.append(task_type)
    
    # File type context (if available)
    if input_files:
        # Extract file extensions
        extensions = set()
        for f in input_files:
            ext = Path(f).suffix.lower()
            if ext:
                extensions.add(ext)
        
        if extensions:
            query_parts.append(" ".join(extensions))
    
    # Build query
    query = " ".join(query_parts)
    
    # Clean query
    query = self._clean_query(query)
    
    logger.info(f"[RAG] Query: {query[:100]}...")
    
    return query

def _clean_query(self, query: str) -> str:
    """Remove noise words and normalize"""
    # Remove common noise words
    noise_words = ['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for']
    
    words = query.split()
    cleaned_words = [w for w in words if w.lower() not in noise_words]
    
    return " ".join(cleaned_words)
```

---

## 📊 EXAMPLE: RAG CONTEXT BUDGET

### **Scenario: Boss Planning PDF Extraction Task**

**Without Filtering:**
```
Total Context Size: 12,000 tokens
├─ Manifest: 2,000 tokens
├─ Work Scope: 3,000 tokens
├─ File Catalog: 1,000 tokens
├─ RAG Results: 6,000 tokens  ❌ TOO MUCH!
└─ Instructions: remaining

Result: Context bloat, slow planning, expensive
```

**With Smart Filtering:**
```
Total Context Size: 7,500 tokens ✅
├─ Manifest: 2,000 tokens
├─ Work Scope: 3,000 tokens
├─ File Catalog: 1,000 tokens
├─ RAG Results: 500 tokens  ✅ BUDGET-COMPLIANT
│   ├─ Learning #1: 200 tokens (similarity: 0.85)
│   ├─ Learning #2: 180 tokens (similarity: 0.78)
│   └─ Learning #3: 120 tokens (similarity: 0.72)
└─ Instructions: 1,000 tokens

Result: Lean context, fast planning, cost-effective
```

---

## 🎯 CONFIGURATION OPTIONS

### **Tunable Parameters:**

```python
RAG_CONFIG = {
    # Retrieval
    "top_k_candidates": 10,           # Initial retrieval size
    
    # Filtering
    "min_similarity": 0.7,            # Only high-confidence (0.7 = 70%)
    "max_results_to_include": 3,      # Max results in final context
    
    # Token Budget
    "max_rag_tokens": 500,            # Hard limit on RAG context
    "min_result_tokens": 100,         # Min tokens per result to be useful
    
    # Task Matching
    "require_task_type_match": True,  # Only similar task types
    "task_type_synonyms": {...},      # Synonym matching
    
    # Safety
    "fail_gracefully": True,          # Continue without RAG on error
    "log_rag_usage": True             # Log for monitoring
}
```

---

## 🔍 EXAMPLE: WHAT GETS INCLUDED

### **Current Task:**
```
Task: "Extract data from TYPE A Pemex PDFs using template"
Type: "batch_process"
Files: ["*.pdf"]
```

### **RAG Search Results (10 candidates):**

| # | Task | Similarity | Token Count | Decision |
|---|------|------------|-------------|----------|
| 1 | develop_template_type_a | 0.89 | 250 | ✅ INCLUDE (high sim, matches type) |
| 2 | batch_process_type_a | 0.84 | 180 | ✅ INCLUDE (high sim, exact match) |
| 3 | extract_pdf_metadata | 0.76 | 200 | ✅ INCLUDE (high sim, related) |
| 4 | transform_csv_data | 0.65 | 150 | ❌ REJECT (low sim, different file type) |
| 5 | process_images | 0.58 | 300 | ❌ REJECT (low sim, different type) |
| 6 | batch_process_type_b | 0.72 | 220 | ⚠️ SKIP (budget exhausted) |
| 7-10 | ... | <0.7 | ... | ❌ REJECT (below threshold) |

### **Final RAG Context: 3 results, ~450 tokens** ✅

---

## 🎯 ADAPTIVE RAG (SMART DEFAULTS)

### **Context-Aware Budgets:**

```python
def _get_rag_budget(self, task_complexity: str, other_context_size: int) -> int:
    """
    Dynamically adjust RAG budget based on task and existing context.
    
    Strategy:
    - Simple tasks: Less RAG (200 tokens)
    - Complex tasks: More RAG (500 tokens)
    - High existing context: Less RAG
    """
    # Base budgets by complexity
    base_budgets = {
        "simple": 200,      # Quick tasks
        "medium": 400,      # Standard tasks
        "complex": 600      # Difficult tasks
    }
    
    base_budget = base_budgets.get(task_complexity, 400)
    
    # Adjust based on existing context
    if other_context_size > 8000:
        # Already lots of context - reduce RAG
        adjusted_budget = int(base_budget * 0.5)
    elif other_context_size > 5000:
        # Moderate context - slight reduction
        adjusted_budget = int(base_budget * 0.75)
    else:
        # Plenty of space - full budget
        adjusted_budget = base_budget
    
    logger.info(f"[RAG] Budget: {adjusted_budget} tokens (complexity={task_complexity}, context_size={other_context_size})")
    
    return adjusted_budget
```

---

## ✅ SAFETY MECHANISMS

### **1. Graceful Degradation:**
```python
# If RAG fails, continue WITHOUT it
try:
    rag_context = await self._query_rag_smart(...)
except Exception as e:
    logger.warning(f"[RAG] Failed, continuing without RAG: {e}")
    rag_context = ""  # Empty - don't block planning
```

### **2. Monitoring & Logging:**
```python
logger.info(f"[RAG] Query: {query[:100]}")
logger.info(f"[RAG] Retrieved: {len(raw_results)} candidates")
logger.info(f"[RAG] Filtered: {len(filtered_results)} high-relevance")
logger.info(f"[RAG] Final: {final_tokens} tokens in context")
```

### **3. Disable RAG Option:**
```python
# In manifest or config
{
    "rag_enabled": true,          # Can be disabled
    "rag_min_similarity": 0.7,    # Configurable
    "rag_max_tokens": 500         # Configurable
}
```

---

## 📊 EXPECTED OUTCOMES

### **Before (Naive RAG):**
- ❌ 10 results × 600 tokens = 6,000 tokens
- ❌ Low-relevance results (similarity 0.3-0.5)
- ❌ Context bloat
- ❌ Expensive, slow

### **After (Smart RAG):**
- ✅ 2-3 results × 150-200 tokens = 400-500 tokens
- ✅ High-relevance only (similarity >0.7)
- ✅ Lean context
- ✅ Fast, cost-effective

---

## 🎯 FINAL ANSWER TO YOUR QUESTIONS

### **Q1: How will auto RAG not overuse context memory?**

**A:** Multi-layer filtering + hard token budget (500 tokens max)
1. Similarity threshold (>0.7) - rejects irrelevant
2. Task type matching - contextual filtering
3. Token budget enforcement - hard limit
4. Truncation - summarize if needed

### **Q2: How do we get only required info?**

**A:** Smart retrieval + aggressive filtering
1. Better queries (task + type + files)
2. Similarity scoring (only high confidence)
3. Task-type matching (only similar tasks)
4. Top-3 limit (most relevant only)
5. Content truncation (essential info only)

---

## 🚀 IMPLEMENTATION

**Start Conservative:**
- Min similarity: 0.75 (high bar)
- Max results: 2 (very selective)
- Max tokens: 400 (tight budget)

**Monitor & Adjust:**
- Track RAG usage in logs
- Measure impact on planning quality
- Tune thresholds based on results

**If RAG Not Helping:**
- Increase min_similarity (more selective)
- Decrease max_tokens (tighter budget)
- Disable for simple tasks

---

**Status:** READY TO IMPLEMENT WITH SMART CONTROLS  
**Risk:** LOW (fail-safe, budget-controlled, monitored)  
**Impact:** HIGH (intelligent planning, knowledge reuse)

