"""`ModalDispatcher` is dead code, retained only for history (RNF-008 gap
closure: Modal/cloud-GPU dispatch removed entirely). Nothing in this codebase
constructs or calls it anymore -- see `evo2_scaling_decision.py`/
`dispatch_hpc_job.py`. This test only pins that the class still exists and
behaves as documented (a loudly-logged mock fallback) in case anything ever
imports it by mistake; it is NOT evidence this is a supported code path.
"""
import logging

import pytest

from src.infrastructure.hpc.modal_dispatcher import ModalDispatcher


@pytest.mark.asyncio
async def test_modal_dispatcher_returns_mock_id_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        job_id = await ModalDispatcher().dispatch("#!/bin/bash\necho hi\n")

    assert job_id == "modal_mock_job"
    assert any("has been REMOVED" in record.message for record in caplog.records)
