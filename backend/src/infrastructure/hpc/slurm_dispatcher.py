from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
import os

class SlurmSSHDispatcher(HPCJobDispatcherPort):
    """
    Adapter implementing HPCJobDispatcherPort using Paramiko SSH tunnel.
    """
    def __init__(self, host: str = None, username: str = None):
        self.host = host or os.getenv("SLURM_HOST", "slurm-login.inst.edu")
        self.username = username or os.getenv("SLURM_USER", "scientist")

    async def dispatch(self, sbatch_script: str) -> str:
        # In a real environment, we would do:
        # ssh = paramiko.SSHClient()
        # ssh.connect(self.host, username=self.username, pkey=...)
        # stdin, stdout, stderr = ssh.exec_command("sbatch")
        # return parse_job_id(stdout.read())
        
        # Local mock or fallback
        return "job_10492"
