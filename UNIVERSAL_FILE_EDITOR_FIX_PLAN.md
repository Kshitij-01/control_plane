# Universal File Editor - Fix Plan

**Based on:** Deep Audit Report (November 1, 2025)  
**Priority:** Address Critical and Medium Issues

---

## 🎯 QUICK FIX OPTION (Recommended)

**Goal:** Fix the 2 most critical issues in ~3-5 hours  
**Deployment:** Production-ready after fixes

### Fix #1: Make Methods Async (Issue #1)

**File:** `control_plane_v2/tools/universal_file_editor.py`

**Change all methods from `def` to `async def` and use `asyncio.to_thread` for I/O:**

```python
import asyncio

@staticmethod
async def search_replace_in_file(...) -> str:
    """Search and replace text in ANY file type."""
    try:
        file = Path(file_path)
        
        # Validate file exists
        if not file.exists():
            return json.dumps({"success": False, "error": f"File not found: {file_path}"})
        
        # Read file content (async)
        content, used_encoding = await asyncio.to_thread(
            cls._read_file_with_encoding_sync, file
        )
        
        if content is None:
            return json.dumps({"success": False, "error": "Could not decode file"})
        
        # ... rest of logic (synchronous) ...
        
        # Write back (async)
        await asyncio.to_thread(
            file.write_text, new_content, encoding=used_encoding or 'utf-8'
        )
        
        return json.dumps({"success": True, ...})
    
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
```

**Apply to all 7 methods:**
- `search_replace_in_file`
- `insert_after_text`
- `insert_before_text`
- `delete_section`
- `read_file_section`
- `create_file_backup`
- `get_file_info`

---

### Fix #2: Add Encoding Helper Method (Issue #2)

**File:** `control_plane_v2/tools/universal_file_editor.py`

**Add helper method for consistent encoding detection:**

```python
@staticmethod
def _read_file_with_encoding_sync(file: Path) -> tuple[str, str]:
    """
    Read file with automatic encoding detection (synchronous).
    Returns (content, encoding) or (None, None) if all encodings fail.
    """
    for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
        try:
            content = file.read_text(encoding=encoding)
            return content, encoding
        except UnicodeDecodeError:
            continue
    return None, None

@staticmethod
def _write_file_with_encoding_sync(file: Path, content: str, encoding: str):
    """Write file with specified encoding (synchronous)."""
    file.write_text(content, encoding=encoding)
```

**Update all methods to use this helper:**

```python
# OLD (inconsistent):
content = file.read_text(encoding='utf-8')

# NEW (consistent):
content, encoding = await asyncio.to_thread(
    cls._read_file_with_encoding_sync, file
)
if content is None:
    return json.dumps({"success": False, "error": "Could not decode file"})
```

---

## 📋 COMPLETE FIX CHECKLIST

### Priority 1: Critical Fixes (3-5 hours)

- [ ] **Fix #1:** Make all methods async
  - [ ] Add `async def` to all 7 methods
  - [ ] Wrap file I/O in `asyncio.to_thread()`
  - [ ] Test async execution
  - [ ] Verify Worker Agent integration

- [ ] **Fix #2:** Add encoding helper
  - [ ] Create `_read_file_with_encoding_sync()` method
  - [ ] Create `_write_file_with_encoding_sync()` method
  - [ ] Update all 7 methods to use helpers
  - [ ] Test with non-UTF-8 files

### Priority 2: Security & UX Fixes (2-3 hours)

- [ ] **Fix #3:** Add path validation (optional)
  - [ ] Create `_validate_file_path()` method
  - [ ] Add workspace_root parameter to all methods
  - [ ] Update TaskAgentTools to pass workspace_root
  - [ ] Test path traversal prevention

- [ ] **Fix #4:** Add newline control
  - [ ] Add `add_newline` parameter to `insert_after_text`
  - [ ] Add `add_newline` parameter to `insert_before_text`
  - [ ] Update documentation
  - [ ] Test inline insertion

- [ ] **Fix #5:** Add occurrence to read_file_section
  - [ ] Add `occurrence` parameter
  - [ ] Update logic to find nth occurrence
  - [ ] Update documentation
  - [ ] Test with multiple matches

### Priority 3: Polish (1-2 hours)

- [ ] **Fix #6:** Standardize error messages
  - [ ] Review all error messages
  - [ ] Ensure all include file path
  - [ ] Consistent formatting

- [ ] **Fix #7:** Add file size limits
  - [ ] Define `MAX_FILE_SIZE = 10MB`
  - [ ] Add size check in all methods
  - [ ] Return helpful error message

- [ ] **Fix #8:** Clarify delete_section docs
  - [ ] Update docstring with clear example
  - [ ] Explain that markers are deleted

- [ ] **Fix #11:** Add logging
  - [ ] Import logging
  - [ ] Add log statements to all methods
  - [ ] Log file path, operation, result

---

## 🚀 IMPLEMENTATION GUIDE

### Step 1: Backup Current Implementation

```bash
cp control_plane_v2/tools/universal_file_editor.py control_plane_v2/tools/universal_file_editor.py.backup
```

### Step 2: Apply Priority 1 Fixes

**Estimated Time:** 3-5 hours

1. Add imports:
```python
import asyncio
import logging
logger = logging.getLogger(__name__)
```

2. Create helper methods:
```python
@staticmethod
def _read_file_with_encoding_sync(file: Path) -> tuple[str, str]:
    # ... implementation ...

@staticmethod
def _write_file_with_encoding_sync(file: Path, content: str, encoding: str):
    # ... implementation ...
```

3. Convert each method to async:
   - Change `def` to `async def`
   - Wrap file reads: `await asyncio.to_thread(cls._read_file_with_encoding_sync, file)`
   - Wrap file writes: `await asyncio.to_thread(cls._write_file_with_encoding_sync, file, content, encoding)`

4. Test each method individually

### Step 3: Test Integration

**Test Script:**

```python
import asyncio
from control_plane_v2.tools.universal_file_editor import UniversalFileEditor

async def test_async_tools():
    # Test search_replace_in_file
    result = await UniversalFileEditor.search_replace_in_file(
        "test.txt", "old", "new", False
    )
    print(result)
    
    # Test insert_after_text
    result = await UniversalFileEditor.insert_after_text(
        "test.txt", "marker", "new content", 1
    )
    print(result)

asyncio.run(test_async_tools())
```

### Step 4: Update Tests

Update `test_universal_file_editor.py` to use async:

```python
async def test_file_operations():
    # ... existing tests but with await ...
    result = await UniversalFileEditor.search_replace_in_file(...)
```

### Step 5: Deploy and Monitor

1. Deploy updated implementation
2. Monitor Worker Agent logs for issues
3. Check for any async-related errors
4. Verify file edits work correctly

---

## 🧪 TESTING STRATEGY

### Unit Tests

```python
import pytest
import asyncio
from pathlib import Path

@pytest.mark.asyncio
async def test_search_replace_async():
    """Test async search_replace_in_file"""
    # Create test file
    test_file = Path("test_async.txt")
    test_file.write_text("Hello World", encoding='utf-8')
    
    # Test async execution
    result = await UniversalFileEditor.search_replace_in_file(
        str(test_file), "Hello", "Hi", False
    )
    
    # Verify
    result_dict = json.loads(result)
    assert result_dict["success"] == True
    assert test_file.read_text() == "Hi World"
    
    # Cleanup
    test_file.unlink()

@pytest.mark.asyncio
async def test_encoding_detection():
    """Test encoding detection with various encodings"""
    # Test UTF-8
    test_file = Path("test_utf8.txt")
    test_file.write_text("Hello 世界", encoding='utf-8')
    result = await UniversalFileEditor.get_file_info(str(test_file))
    assert json.loads(result)["success"] == True
    test_file.unlink()
    
    # Test Latin-1
    test_file = Path("test_latin1.txt")
    test_file.write_text("Café", encoding='latin-1')
    result = await UniversalFileEditor.get_file_info(str(test_file))
    assert json.loads(result)["success"] == True
    test_file.unlink()
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_worker_agent_integration():
    """Test that Worker Agent can call async file editing tools"""
    # This requires full Worker Agent setup
    # Test that tools are called correctly via _execute_tool_calls
    pass
```

---

## 📊 RISK MITIGATION

### Rollback Plan

If async changes cause issues:

1. **Immediate Rollback:**
   ```bash
   cp control_plane_v2/tools/universal_file_editor.py.backup control_plane_v2/tools/universal_file_editor.py
   ```

2. **Partial Rollback:**
   - Keep encoding fixes
   - Revert async changes
   - Use sync methods with fallback path

### Monitoring

After deployment, monitor:
- Worker Agent logs for async errors
- File edit success rate
- Execution time (should be similar or faster)
- Memory usage (should be unchanged)

---

## 🎯 SUCCESS CRITERIA

### Must Have (Priority 1)
- ✅ All methods are async
- ✅ File I/O doesn't block event loop
- ✅ Encoding detection works for all file types
- ✅ Worker Agent can call tools successfully
- ✅ All existing functionality preserved

### Should Have (Priority 2)
- ✅ Path validation prevents traversal attacks
- ✅ Insert methods support inline insertion
- ✅ read_file_section supports multiple occurrences

### Nice to Have (Priority 3)
- ✅ Logging for all operations
- ✅ File size limits
- ✅ Standardized error messages

---

## 📅 TIMELINE

### Option A: Quick Fix (Recommended)
- **Day 1 (3-5 hours):** Implement Priority 1 fixes
- **Day 1 (1 hour):** Test and verify
- **Day 1:** Deploy to production

### Option B: Complete Fix
- **Day 1 (3-5 hours):** Implement Priority 1 fixes
- **Day 2 (2-3 hours):** Implement Priority 2 fixes
- **Day 2 (1-2 hours):** Implement Priority 3 fixes
- **Day 2 (2 hours):** Comprehensive testing
- **Day 3:** Deploy to production

---

## 🤝 DECISION NEEDED

**Which option do you prefer?**

1. **Deploy As-Is** - Use current implementation, fix issues as they arise
2. **Quick Fix (Recommended)** - Fix async/encoding issues (3-5 hours), then deploy
3. **Complete Fix** - Fix all identified issues (2 days), then deploy

**Recommendation:** **Option 2 (Quick Fix)** provides the best balance of:
- ✅ Addresses critical issues
- ✅ Reasonable time investment (3-5 hours)
- ✅ Production-ready after fixes
- ✅ Can add Priority 2/3 fixes later if needed

---

**Fix Plan Created:** November 1, 2025  
**Status:** Ready for Implementation

