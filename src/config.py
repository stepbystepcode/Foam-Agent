# config.py
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Config:
    max_loop: int = 50
    
    batchsize: int = 10
    searchdocs: int = 2
    run_times: int = 1  # current run number (for directory naming)
    database_path: str = Path(__file__).resolve().parent.parent / "database"
    run_directory: str = Path(__file__).resolve().parent.parent / "runs"
    case_dir: str = ""
    max_time_limit = 36000 # Max time limit after which the openfoam run will be terminated
    model_provider: str = "deepseek" # [openai, bedrock, ollama, deepseek]
    # model_provider: str = "ollama" # [openai, bedrock, ollama, deepseek]
    # model_version should be in ["arn:aws:bedrock:us-west-2:991404956194:application-inference-profile/56i8iq1vib3e", "gpt-4o", "deepseek-r1:32b-qwen-distill-fp16"]
    model_version: str = "deepseek-chat"
    # model_version: str = "qwen3:235b-a22b-q4_K_M"
    temperature: float = 0.6
    
