# 🎯 Interactive TODO List Enhancement

## Problem Identified

**User Observation:** "The worker never adds tasks, only marks it done at end. I want the list to be more interactive - Claude should add tasks to list, mark some tasks complete and keep other pending if they are pending."

**Root Cause:** The Worker's system prompt only instructed:
- Attempt #1: CREATE list (merge=false)
- Attempt #2+: UPDATE status (merge=true)

This was too vague and didn't emphasize the **INTERACTIVE** nature of TODO management.

---

## Solution Implemented

### 1. Enhanced System Prompt - Interactive TODO Section

**Before:**
```
Management:
- Attempt #1: CREATE list (merge=false) - MUST BE FIRST ACTION
- Attempt #2+: UPDATE status (merge=true) as you complete tasks
- System BLOCKS success if ANY TODO incomplete
- Mark: pending -> in_progress -> completed
```

**After:**
```
=== MANDATORY: INTERACTIVE TODO LIST (LIVE TRACKING) ===

⚠️ CRITICAL: TODO list must be ACTIVELY MANAGED throughout execution!

🎯 ATTEMPT #1 - CREATE TODO LIST (BEFORE ANY CODE):
1. Find "MANDATORY TODO LIST (Boss-Created)" section in instructions
2. Extract the JSON array from Boss's instructions
3. IMMEDIATELY call todo_write_function with:
   - workspace_path: (from Boss's instructions)
   - merge: false (creates new list)
   - todos: (Boss's JSON array, all status="pending")
4. Wait for tool result
5. THEN write exploration code

📋 ATTEMPT #2+ - UPDATE TODO LIST INTERACTIVELY:

BEFORE starting a task:
→ Call todo_write_function(merge=true, todos=[{id: "task_1", status: "in_progress", ...}])
→ This shows you're actively working on it

AFTER completing a task:
→ Call todo_write_function(merge=true, todos=[{id: "task_1", status: "completed", ...}])
→ This tracks your progress

IF you discover new subtasks:
→ Call todo_write_function(merge=true, todos=[{id: "task_4_new", status: "pending", content: "New task", ...}])
→ This adds to the list

🔄 INTERACTIVE WORKFLOW EXAMPLE:

Attempt #1:
- Call todo_write_function(merge=false, todos=[task1, task2, task3]) ← CREATE
- Explore data, print samples

Attempt #2:
- Call todo_write_function(merge=true, todos=[{id: "task1", status: "in_progress"}]) ← START
- Work on task 1
- Call todo_write_function(merge=true, todos=[{id: "task1", status: "completed"}]) ← FINISH

Attempt #3:
- Call todo_write_function(merge=true, todos=[{id: "task2", status: "in_progress"}]) ← START
- Work on task 2
- Discover task 2 needs subtasks
- Call todo_write_function(merge=true, todos=[{id: "task2a", status: "pending", content: "Subtask A"}]) ← ADD NEW

Attempt #4:
- Call todo_write_function(merge=true, todos=[{id: "task2", status: "completed"}]) ← FINISH
- Continue...

⚠️ CRITICAL RULES:
- System BLOCKS success if ANY TODO is "pending" or "in_progress"
- You MUST mark ALL tasks "completed" before claiming success
- Update the list MULTIPLE times per attempt if needed
- The TODO list is your PROGRESS TRACKER - keep it current!

TOOL SYNTAX:
- Just call the tool - no special syntax needed
- You can call it MULTIPLE times in one attempt
- Each call updates the workspace TODO list file
```

### 2. Enhanced Checklist

**Before:**
```
- If retry=false: Included verification_summary? Used 2+ attempts? ALL TODOs completed?
```

**After:**
```
📋 TODO LIST:
- Attempt #1? Called todo_write_function(merge=false) to CREATE the list?
- Attempt #2+? Called todo_write_function(merge=true) to UPDATE task status?
- Starting a new task? Marked it "in_progress" BEFORE working on it?
- Finished a task? Marked it "completed" AFTER finishing?
- Discovered new subtasks? Added them with "pending" status?

📁 FILE CREATION:
- Created ALL files Boss requested?
- LOADED actual data samples and checked if they MAKE SENSE for the task?
[... rest of file checks ...]

✅ BEFORE CLAIMING SUCCESS (retry=false):
- Used 2+ attempts? (Attempt #1 is always exploration)
- ALL TODOs marked "completed"? (No "pending" or "in_progress")
- Included verification_summary? (3+ sentences about ACTUAL data observed)
- If data doesn't make sense or is mostly empty: Set retry=true and FIX the logic
```

---

## Expected Behavior After Enhancement

### Worker's Interactive TODO Workflow:

**Attempt #1: Initialization**
```python
# Worker calls todo_write_function
todo_write_function(
    workspace_path="/path/to/workspace",
    merge=False,  # Create new list
    todos=[
        {"id": "task1", "status": "pending", "content": "Extract PDF text"},
        {"id": "task2", "status": "pending", "content": "Parse data into JSON"},
        {"id": "task3", "status": "pending", "content": "Generate HTML report"}
    ]
)
# Then explores data
```

**Attempt #2: Start Task 1**
```python
# Mark task 1 as in_progress
todo_write_function(
    workspace_path="/path/to/workspace",
    merge=True,  # Update existing
    todos=[{"id": "task1", "status": "in_progress"}]
)

# Work on extracting PDF text
# ... code ...

# Mark task 1 as completed
todo_write_function(
    workspace_path="/path/to/workspace",
    merge=True,
    todos=[{"id": "task1", "status": "completed"}]
)
```

**Attempt #3: Start Task 2, Discover Subtasks**
```python
# Mark task 2 as in_progress
todo_write_function(merge=True, todos=[{"id": "task2", "status": "in_progress"}])

# While working, discovers task 2 needs subtasks
todo_write_function(
    merge=True,
    todos=[
        {"id": "task2a", "status": "pending", "content": "Parse metadata"},
        {"id": "task2b", "status": "pending", "content": "Parse events"}
    ]
)

# Complete subtask 2a
todo_write_function(merge=True, todos=[{"id": "task2a", "status": "completed"}])
```

**Attempt #4: Continue Task 2**
```python
# Complete subtask 2b
todo_write_function(merge=True, todos=[{"id": "task2b", "status": "completed"}])

# Complete main task 2
todo_write_function(merge=True, todos=[{"id": "task2", "status": "completed"}])
```

**Attempt #5: Final Task**
```python
# Mark task 3 as in_progress
todo_write_function(merge=True, todos=[{"id": "task3", "status": "in_progress"}])

# Generate HTML
# ... code ...

# Mark task 3 as completed
todo_write_function(merge=True, todos=[{"id": "task3", "status": "completed"}])

# Verify all tasks completed
# Claim success (retry=false)
```

---

## Key Improvements

1. ✅ **Explicit Instructions:** Clear step-by-step workflow with examples
2. ✅ **Multiple Updates Per Attempt:** Worker can call `todo_write_function` multiple times
3. ✅ **Status Transitions:** Explicit instructions to mark tasks as:
   - `pending` → `in_progress` (when starting)
   - `in_progress` → `completed` (when done)
4. ✅ **Dynamic Task Addition:** Instructions to add new tasks discovered during work
5. ✅ **Visual Examples:** Concrete workflow showing 5 attempts with TODO updates
6. ✅ **Enhanced Checklist:** Separate TODO section in pre-response checklist
7. ✅ **Emphasis on Interactivity:** "ACTIVELY MANAGED" and "LIVE TRACKING" language

---

## Files Modified

- `control_plane_v2/phase_2/worker_agent_autonomous.py`
  - Lines 82-140: Enhanced TODO section with interactive workflow
  - Lines 212-234: Enhanced checklist with TODO-specific items

---

## Testing Recommendations

1. **Monitor TODO File Updates:** Check `worker_todos.json` is updated multiple times during execution
2. **Verify Status Transitions:** Ensure tasks go through `pending` → `in_progress` → `completed`
3. **Check Dynamic Additions:** Verify Worker adds new tasks when discovering subtasks
4. **Validate Blocking:** Confirm system blocks success if any TODO is not "completed"

---

## Expected Impact

- **Better Progress Tracking:** Users can see real-time progress through TODO list
- **More Granular Visibility:** Each task's status is visible as Worker progresses
- **Dynamic Planning:** Worker can break down complex tasks into subtasks on-the-fly
- **Improved Debugging:** If Worker gets stuck, TODO list shows exactly where
- **Better User Experience:** Interactive progress updates instead of "black box" execution

---

## Status

✅ **IMPLEMENTED** - Ready for testing in next run

