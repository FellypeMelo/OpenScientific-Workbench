"""Unit tests for `SandboxNodeExecutor` (RF-005/RNF-001/RNF-002).

The injected sandbox driver is a hand-written fake (recording calls, returning
canned `(stdout, exit_code)` tuples) -- the actual transport boundary
(subprocess/bwrap) is covered by `test_bubblewrap_driver.py`; this suite is
purely about `SandboxNodeExecutor`'s own dispatch/reward-mapping logic, so
faking the driver port here (not business logic) is the correct boundary.
"""
import os

import pytest

from src.domain.entities.dag import DAGNode
from src.infrastructure.sandbox.sandbox_node_executor import SandboxNodeExecutor


class _FakeDriver:
    def __init__(self, workspace_root="fake_workspace"):
        self.workspace_root = workspace_root
        self.calls = []
        self.python_result = ("42\n", 0)
        self.bash_result = ("hi\n", 0)
        self.r_result = ('[1] "hi"\n', 0)
        self.raise_error: Exception | None = None

    def execute_python_script(self, relative_script_path: str):
        self.calls.append(("python", relative_script_path))
        if self.raise_error:
            raise self.raise_error
        return self.python_result

    def execute_bash(self, command: str):
        self.calls.append(("bash", command))
        if self.raise_error:
            raise self.raise_error
        return self.bash_result

    def execute_r_script(self, code: str):
        self.calls.append(("r", code))
        if self.raise_error:
            raise self.raise_error
        return self.r_result


@pytest.mark.asyncio
async def test_bash_node_success_maps_to_positive_reward():
    driver = _FakeDriver()
    driver.bash_result = ("hi\n", 0)
    node = DAGNode(id="n1", description="say hi", language="bash", command="echo hi")

    reward = await SandboxNodeExecutor(driver).simulate(node)

    assert reward == 1.0
    assert node.output == {"stdout": "hi\n", "exit_code": 0}
    assert driver.calls == [("bash", "echo hi")]


@pytest.mark.asyncio
async def test_bash_node_nonzero_exit_maps_to_negative_reward():
    driver = _FakeDriver()
    driver.bash_result = ("Execution error: boom", 1)
    node = DAGNode(id="n1", description="fail", language="bash", command="false")

    reward = await SandboxNodeExecutor(driver).simulate(node)

    assert reward == -1.0
    assert node.output == {"stdout": "Execution error: boom", "exit_code": 1}


@pytest.mark.asyncio
async def test_r_node_dispatches_to_execute_r_script():
    driver = _FakeDriver()
    node = DAGNode(id="n1", description="r stuff", language="R", command="print('hi')")

    reward = await SandboxNodeExecutor(driver).simulate(node)

    assert reward == 1.0
    assert driver.calls == [("r", "print('hi')")]


@pytest.mark.asyncio
async def test_python_node_materializes_script_file_and_dispatches(tmp_path):
    driver = _FakeDriver(workspace_root=str(tmp_path))
    node = DAGNode(
        id="n-1_weird id!",
        description="compute",
        language="python",
        command="print(42)",
    )

    reward = await SandboxNodeExecutor(driver).simulate(node)

    assert reward == 1.0
    assert len(driver.calls) == 1
    kind, rel_path = driver.calls[0]
    assert kind == "python"

    written_path = os.path.join(str(tmp_path), rel_path)
    assert os.path.exists(written_path)
    with open(written_path, encoding="utf-8") as fh:
        assert fh.read() == "print(42)"


@pytest.mark.asyncio
async def test_empty_command_prunes_without_calling_driver():
    driver = _FakeDriver()
    node = DAGNode(id="n1", description="nothing", language="bash", command="")

    reward = await SandboxNodeExecutor(driver).simulate(node)

    assert reward == -1.0
    assert driver.calls == []
    assert "error" in node.output


@pytest.mark.asyncio
async def test_unsupported_language_prunes_without_calling_driver():
    driver = _FakeDriver()
    node = DAGNode(id="n1", description="?", language="perl", command="print 1")

    reward = await SandboxNodeExecutor(driver).simulate(node)

    assert reward == -1.0
    assert driver.calls == []
    assert "Unsupported language" in node.output["error"]


@pytest.mark.asyncio
async def test_driver_permission_error_prunes_gracefully():
    driver = _FakeDriver()
    driver.raise_error = PermissionError("FATAL_SANDBOX_PATH_VIOLATION: blocked")
    node = DAGNode(id="n1", description="escape attempt", language="bash", command="cat /etc/passwd")

    reward = await SandboxNodeExecutor(driver).simulate(node)

    assert reward == -1.0
    assert "blocked" in node.output["error"]


@pytest.mark.asyncio
async def test_driver_os_error_prunes_gracefully():
    driver = _FakeDriver()
    driver.raise_error = OSError("sandbox unavailable")
    node = DAGNode(id="n1", description="x", language="bash", command="echo hi")

    reward = await SandboxNodeExecutor(driver).simulate(node)

    assert reward == -1.0
    assert "sandbox unavailable" in node.output["error"]
