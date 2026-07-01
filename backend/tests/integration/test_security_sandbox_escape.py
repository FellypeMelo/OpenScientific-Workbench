import pytest
from src.infrastructure.sandbox.gvisor_driver import GVisorSandboxDriver

def test_security_sandbox_escape_vectors():
    driver = GVisorSandboxDriver()
    
    # Escape vectors representing CVE-2026-7398 and CWE-22 attacks
    payloads = [
        "../../etc/passwd",
        "/etc/shadow",
        "\\Windows\\System32",
        "workspace_1/../../../home",
        "../../var/log"
    ]
    
    for payload in payloads:
        with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
            driver.execute_python_script(payload)
