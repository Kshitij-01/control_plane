#!/usr/bin/env python
"""Test if Jupyter kernel works"""

from jupyter_client import KernelManager
import time

print("Testing Jupyter kernel...")

try:
    km = KernelManager(kernel_name='python3')
    km.start_kernel()
    print("[OK] Kernel started successfully")
    
    kc = km.client()
    kc.start_channels()
    kc.wait_for_ready(timeout=10)
    print("[OK] Kernel is ready")
    
    # Execute simple code
    msg_id = kc.execute("print('Hello from kernel')")
    print("[OK] Code executed")
    
    # Get output
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=5)
            if msg['msg_type'] == 'stream':
                print(f"[OK] Output: {msg['content']['text']}")
                break
        except:
            break
    
    kc.stop_channels()
    km.shutdown_kernel()
    print("[OK] Kernel shut down successfully")
    print("\n=== KERNEL TEST PASSED ===")
    
except Exception as e:
    print(f"[FAIL] Error: {type(e).__name__}: {e}")
    print("\n=== KERNEL TEST FAILED ===")

