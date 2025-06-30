# utils.py
import re
import subprocess
import os
from typing import Optional, Any, Type
from pydantic import BaseModel
from langchain.chat_models import init_chat_model
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import OllamaEmbeddings
from langchain_aws import ChatBedrock, ChatBedrockConverse
from langchain_anthropic import ChatAnthropic
from pathlib import Path
import tracking_aws
import requests
from pydantic import BaseModel, Field
from typing import List
import time
import random
from botocore.exceptions import ClientError
import shutil
from config import Config
from langchain_ollama import ChatOllama
from langchain_deepseek.chat_models import ChatDeepSeek
import dotenv
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.openai import OpenAI
langfuse = Langfuse(
    public_key="pk-lf-937d1b70-a126-4702-9265-f8f349ae0fbc",
    secret_key="sk-lf-e9e5be34-58e3-4418-ae0b-11fb824a556d",
    host="https://cloud.langfuse.com"
)

langfuse_handler = CallbackHandler()
# 加载.env文件中的环境变量
dotenv.load_dotenv()

# Global dictionary to store loaded FAISS databases
FAISS_DB_CACHE = {}
DATABASE_DIR = f"{Path(__file__).resolve().parent.parent}/database/faiss"

embeddings = OllamaEmbeddings(model="nomic-embed-text", base_url="http://localhost:11434", num_gpu=4)

FAISS_DB_CACHE = {
    "openfoam_allrun_scripts": FAISS.load_local(f"{DATABASE_DIR}/openfoam_allrun_scripts", embeddings, allow_dangerous_deserialization=True),
    "openfoam_tutorials_structure": FAISS.load_local(f"{DATABASE_DIR}/openfoam_tutorials_structure", embeddings, allow_dangerous_deserialization=True),
    "openfoam_tutorials_details": FAISS.load_local(f"{DATABASE_DIR}/openfoam_tutorials_details", embeddings, allow_dangerous_deserialization=True),
    "openfoam_command_help": FAISS.load_local(f"{DATABASE_DIR}/openfoam_command_help", embeddings, allow_dangerous_deserialization=True)
}

class FoamfilePydantic(BaseModel):
    file_name: str = Field(description="Name of the OpenFOAM input file")
    folder_name: str = Field(description="Folder where the foamfile should be stored")
    content: str = Field(description="Content of the OpenFOAM file, written in OpenFOAM dictionary format")

class FoamPydantic(BaseModel):
    list_foamfile: List[FoamfilePydantic] = Field(description="List of OpenFOAM configuration files")

class ResponseWithThinkPydantic(BaseModel):
    think: str = Field(description="Thought process of the LLM")
    response: str = Field(description="Response of the LLM")
    
class LLMService:
    def __init__(self, config: object):
        self.model_version = getattr(config, "model_version", "gpt-4o")
        self.temperature = getattr(config, "temperature", 0)
        self.model_provider = getattr(config, "model_provider", "openai")
        
        # Initialize statistics
        self.total_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.failed_calls = 0
        self.retry_count = 0
        
        # Initialize the LLM
        if self.model_provider.lower() == "bedrock":
            bedrock_runtime = tracking_aws.new_default_client()
            self.llm = ChatBedrockConverse(
                client=bedrock_runtime, 
                model_id=self.model_version, 
                temperature=self.temperature, 
                max_tokens=8192
            )
        elif self.model_provider.lower() == "anthropic":
            self.llm = ChatAnthropic(
                model=self.model_version, 
                temperature=self.temperature
            )
        elif self.model_provider.lower() == "openai":
            self.llm = init_chat_model(
                self.model_version, 
                model_provider=self.model_provider, 
                temperature=self.temperature
            )

        elif self.model_provider.lower() == "deepseek":
            # 从环境变量获取DEEPSEEK_API_KEY
            deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
            if not deepseek_api_key:
                print("警告: 未找到DEEPSEEK_API_KEY环境变量")
            
            self.llm = ChatDeepSeek(
                model=self.model_version,
                temperature=self.temperature,
                api_key=deepseek_api_key,
            )
        elif self.model_provider.lower() == "ollama":
            print("ollama")
            try:
                response = requests.get("http://localhost:11434/api/version", timeout=2)
                # If request successful, service is running
            except requests.exceptions.RequestException:
                print("Ollama is not running, starting it...")
                subprocess.Popen(["ollama", "serve"], 
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
                # Wait for service to start
                time.sleep(5)  # Give it 3 seconds to initialize

            self.llm = ChatOllama(
                model=self.model_version, 
                temperature=self.temperature,
                num_predict=-1,
                num_ctx=40960,
                base_url="http://10.108.201.190:11434",
                callbacks=[langfuse_handler]
            )
        else:
            raise ValueError(f"{self.model_provider} is not a supported model_provider")
    
    def invoke(self, 
              user_prompt: str, 
              system_prompt: Optional[str] = None, 
              pydantic_obj: Optional[Type[BaseModel]] = None,
              max_retries: int = 10) -> Any:
        """
        Invoke the LLM with the given prompts and return the response.
        
        Args:
            user_prompt: The user's prompt
            system_prompt: Optional system prompt
            pydantic_obj: Optional Pydantic model for structured output
            max_retries: Maximum number of retries for throttling errors
            
        Returns:
            The LLM response with token usage statistics
        """
        self.total_calls += 1
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        # Calculate prompt tokens
        prompt_tokens = 0
        if self.model_provider.lower() == "ollama":
            # For Ollama, use a simple approximation based on characters
            for message in messages:
                # Approximate token count (roughly 4 chars per token)
                prompt_tokens += len(message["content"]) // 4
        else:
            try:
                for message in messages:
                    prompt_tokens += self.llm.get_num_tokens(message["content"])
            except Exception as e:
                print(f"Warning: Token counting error: {e}")
                # Fallback approximation if tokenizer fails
                for message in messages:
                    prompt_tokens += len(message["content"]) // 4
        
        retry_count = 0
        while True:
            try:
                if pydantic_obj:
                    structured_llm = self.llm.with_structured_output(pydantic_obj)
                    response = structured_llm.invoke(messages)
                else:
                    if self.model_version.startswith("deepseek"):
                        structured_llm = self.llm.with_structured_output(ResponseWithThinkPydantic)
                        response = structured_llm.invoke(messages)

                        # Extract the resposne without the think
                        response = response.response
                    else:
                        response = self.llm.invoke(messages)
                        response = response.content

                # Calculate completion tokens
                response_content = str(response)
                if self.model_provider.lower() == "ollama":
                    # For Ollama, use a simple approximation based on characters
                    completion_tokens = len(response_content) // 4
                else:
                    try:
                        completion_tokens = self.llm.get_num_tokens(response_content)
                    except Exception as e:
                        print(f"Warning: Token counting error: {e}")
                        # Fallback approximation if tokenizer fails
                        completion_tokens = len(response_content) // 4
                total_tokens = prompt_tokens + completion_tokens
                
                # Update statistics
                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                self.total_tokens += total_tokens
                
                return response
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'Throttling' or e.response['Error']['Code'] == 'TooManyRequestsException':
                    retry_count += 1
                    self.retry_count += 1
                    
                    if retry_count > max_retries:
                        self.failed_calls += 1
                        raise Exception(f"Maximum retries ({max_retries}) exceeded: {str(e)}")
                    
                    base_delay = 1.0
                    max_delay = 60.0
                    delay = min(max_delay, base_delay * (2 ** (retry_count - 1)))
                    jitter = random.uniform(0, 0.1 * delay)
                    sleep_time = delay + jitter
                    
                    print(f"ThrottlingException occurred: {str(e)}. Retrying in {sleep_time:.2f} seconds (attempt {retry_count}/{max_retries})")
                    time.sleep(sleep_time)
                else:
                    self.failed_calls += 1
                    raise e
            except Exception as e:
                self.failed_calls += 1
                raise e
    
    def get_statistics(self) -> dict:
        """
        Get the current statistics of the LLM service.
        
        Returns:
            Dictionary containing various statistics
        """
        return {
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "retry_count": self.retry_count,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "average_prompt_tokens": self.total_prompt_tokens / self.total_calls if self.total_calls > 0 else 0,
            "average_completion_tokens": self.total_completion_tokens / self.total_calls if self.total_calls > 0 else 0,
            "average_tokens": self.total_tokens / self.total_calls if self.total_calls > 0 else 0
        }
    
    def print_statistics(self) -> None:
        """
        Print the current statistics of the LLM service.
        """
        stats = self.get_statistics()
        print("\n<LLM Service Statistics>")
        print(f"Total calls: {stats['total_calls']}")
        print(f"Failed calls: {stats['failed_calls']}")
        print(f"Total retries: {stats['retry_count']}")
        print(f"Total prompt tokens: {stats['total_prompt_tokens']}")
        print(f"Total completion tokens: {stats['total_completion_tokens']}")
        print(f"Total tokens: {stats['total_tokens']}")
        print(f"Average prompt tokens per call: {stats['average_prompt_tokens']:.2f}")
        print(f"Average completion tokens per call: {stats['average_completion_tokens']:.2f}")
        print(f"Average tokens per call: {stats['average_tokens']:.2f}\n")
        print("</LLM Service Statistics>")

def tokenize(text: str) -> str:
    # Replace underscores with spaces
    text = text.replace('_', ' ')
    # Insert a space between a lowercase letter and an uppercase letter (global match)
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)
    return text.lower()

def save_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    print(f"Saved file at {path}")

def read_file(path: str) -> str:
    if os.path.exists(path):
        with open(path, 'r') as f:
            return f.read()
    return ""

def list_case_files(case_dir: str) -> str:
    files = [f for f in os.listdir(case_dir) if os.path.isfile(os.path.join(case_dir, f))]
    return ", ".join(files)

def remove_files(directory: str, prefix: str) -> None:
    for file in os.listdir(directory):
        if file.startswith(prefix):
            os.remove(os.path.join(directory, file))
    print(f"Removed files with prefix '{prefix}' in {directory}")

def remove_file(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
        print(f"Removed file {path}")

def remove_numeric_folders(case_dir: str) -> None:
    """
    Remove all folders in case_dir that represent numeric values, including those with decimal points,
    except for the "0" folder.
    
    Args:
        case_dir (str): The directory path to process
    """
    for item in os.listdir(case_dir):
        item_path = os.path.join(case_dir, item)
        if os.path.isdir(item_path) and item != "0":
            try:
                # Try to convert to float to check if it's a numeric value
                float(item)
                # If conversion succeeds, it's a numeric folder
                try:
                    shutil.rmtree(item_path)
                    print(f"Removed numeric folder: {item_path}")
                except Exception as e:
                    print(f"Error removing folder {item_path}: {str(e)}")
            except ValueError:
                # Not a numeric value, so we keep this folder
                pass

def run_command(script_path: str, out_file: str, err_file: str, working_dir: str, config : Config) -> None:
    print(f"Executing script {script_path} in {working_dir}")
    os.chmod(script_path, 0o777)
    openfoam_dir = os.getenv("WM_PROJECT_DIR")
    command = f"source {openfoam_dir}/etc/bashrc && bash {os.path.abspath(script_path)}"
    timeout_seconds = config.max_time_limit

    with open(out_file, 'w') as out, open(err_file, 'w') as err:
        process = subprocess.Popen(
            ['bash', "-c", command],
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True
        )
        # stdout, stderr = process.communicate()
        # out.write(stdout)
        # err.write(stderr)

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            out.write(stdout)
            err.write(stderr)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            timeout_message = (
                "OpenFOAM execution took too long. "
                "This case, if set up right, does not require such large execution times.\n"
            )
            out.write(timeout_message + stdout)
            err.write(timeout_message + stderr)
            print(f"Execution timed out: {script_path}")

    

    print(f"Executed script {script_path}")

def check_foam_errors(directory: str) -> list:
    error_logs = []
    # DOTALL mode allows '.' to match newline characters
    pattern = re.compile(r"ERROR:(.*)", re.DOTALL)
    
    for file in os.listdir(directory):
        if file.startswith("log"):
            filepath = os.path.join(directory, file)
            with open(filepath, 'r') as f:
                content = f.read()
            
            match = pattern.search(content)
            if match:
                error_content = match.group(0).strip()
                error_logs.append({"file": file, "error_content": error_content})
            elif "error" in content.lower():
                print(f"Warning: file {file} contains 'error' but does not match expected format.")
    return error_logs

def extract_commands_from_allrun_out(out_file: str) -> list:
    commands = []
    if not os.path.exists(out_file):
        return commands
    with open(out_file, 'r') as f:
        for line in f:
            if line.startswith("Running "):
                parts = line.split(" ")
                if len(parts) > 1:
                    commands.append(parts[1].strip())
    return commands

def parse_case_name(text: str) -> str:
    match = re.search(r'case name:\s*(.+)', text, re.IGNORECASE)
    return match.group(1).strip() if match else "default_case"

def split_subtasks(text: str) -> list:
    header_match = re.search(r'splits into (\d+) subtasks:', text, re.IGNORECASE)
    if not header_match:
        print("Warning: No subtasks header found in the response.")
        return []
    num_subtasks = int(header_match.group(1))
    subtasks = re.findall(r'subtask\d+:\s*(.*)', text, re.IGNORECASE)
    if len(subtasks) != num_subtasks:
        print(f"Warning: Expected {num_subtasks} subtasks but found {len(subtasks)}.")
    return subtasks

def parse_context(text: str) -> str:
    match = re.search(r'FoamFile\s*\{.*?(?=```|$)', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()
    
    print("Warning: Could not parse context; returning original text.")
    return text


def parse_file_name(subtask: str) -> str:
    match = re.search(r'openfoam\s+(.*?)\s+foamfile', subtask, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def parse_folder_name(subtask: str) -> str:
    match = re.search(r'foamfile in\s+(.*?)\s+folder', subtask, re.IGNORECASE)
    return match.group(1).strip() if match else ""

def find_similar_file(description: str, tutorial: str) -> str:
    start_pos = tutorial.find(description)
    if start_pos == -1:
        return "None"
    end_marker = "input_file_end."
    end_pos = tutorial.find(end_marker, start_pos)
    if end_pos == -1:
        return "None"
    return tutorial[start_pos:end_pos + len(end_marker)]

def read_commands(file_path: str) -> str:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Commands file not found: {file_path}")
    with open(file_path, 'r') as f:
        # join non-empty lines with a comma
        return ", ".join(line.strip() for line in f if line.strip())

def find_input_file(case_dir: str, command: str) -> str:
    for root, _, files in os.walk(case_dir):
        for file in files:
            if command in file:
                return os.path.join(root, file)
    return ""

def retrieve_faiss(database_name: str, query: str, topk: int = 1) -> dict:
    """
    Retrieve a similar case from a FAISS database.
    """
    
    if database_name not in FAISS_DB_CACHE:
        raise ValueError(f"Database '{database_name}' is not loaded.")
    
    # Tokenize the query
    query = tokenize(query)
    
    vectordb = FAISS_DB_CACHE[database_name]
    docs = vectordb.similarity_search(query, k=topk)
    if not docs:
        raise ValueError(f"No documents found for query: {query}")
    
    formatted_results = []
    for doc in docs:
        metadata = doc.metadata or {}
        
        if database_name == "openfoam_allrun_scripts":
            formatted_results.append({
                "index": doc.page_content,
                "full_content": metadata.get("full_content", "unknown"),
                "case_name": metadata.get("case_name", "unknown"),
                "case_domain": metadata.get("case_domain", "unknown"),
                "case_category": metadata.get("case_category", "unknown"),
                "case_solver": metadata.get("case_solver", "unknown"),
                "dir_structure": metadata.get("dir_structure", "unknown"),
                "allrun_script": metadata.get("allrun_script", "N/A")
            })
        elif database_name == "openfoam_command_help":
            formatted_results.append({
                "index": doc.page_content,
                "full_content": metadata.get("full_content", "unknown"),
                "command": metadata.get("command", "unknown"),
                "help_text": metadata.get("help_text", "unknown")
            })
        elif database_name == "openfoam_tutorials_structure":
            formatted_results.append({
                "index": doc.page_content,
                "full_content": metadata.get("full_content", "unknown"),
                "case_name": metadata.get("case_name", "unknown"),
                "case_domain": metadata.get("case_domain", "unknown"),
                "case_category": metadata.get("case_category", "unknown"),
                "case_solver": metadata.get("case_solver", "unknown"),
                "dir_structure": metadata.get("dir_structure", "unknown")
            })
        elif database_name == "openfoam_tutorials_details":
            formatted_results.append({
                "index": doc.page_content,
                "full_content": metadata.get("full_content", "unknown"),
                "case_name": metadata.get("case_name", "unknown"),
                "case_domain": metadata.get("case_domain", "unknown"),
                "case_category": metadata.get("case_category", "unknown"),
                "case_solver": metadata.get("case_solver", "unknown"),
                "dir_structure": metadata.get("dir_structure", "unknown"),
                "tutorials": metadata.get("tutorials", "N/A")
            })
        else:
            raise ValueError(f"Unknown database name: {database_name}")
    
    

    return formatted_results
        

def parse_directory_structure(data: str) -> dict:
    """
    Parses the directory structure string and returns a dictionary where:
      - Keys: directory names
      - Values: count of files in that directory.
    """
    directory_file_counts = {}

    # Find all <dir>...</dir> blocks in the input string.
    dir_blocks = re.findall(r'<dir>(.*?)</dir>', data, re.DOTALL)

    for block in dir_blocks:
        # Extract the directory name (everything after "directory name:" until the first period)
        dir_name_match = re.search(r'directory name:\s*(.*?)\.', block)
        # Extract the list of file names within square brackets
        files_match = re.search(r'File names in this directory:\s*\[(.*?)\]', block)
        
        if dir_name_match and files_match:
            dir_name = dir_name_match.group(1).strip()
            files_str = files_match.group(1)
            # Split the file names by comma, removing any surrounding whitespace
            file_list = [filename.strip() for filename in files_str.split(',')]
            directory_file_counts[dir_name] = len(file_list)

    return directory_file_counts
