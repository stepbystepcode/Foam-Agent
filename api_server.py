#!/usr/bin/env python3
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
import subprocess
import os
import sys
import shlex
import threading
import datetime
from pathlib import Path
import uvicorn

app = FastAPI(title="Foam-Agent API", description="API for controlling foambench_main.py execution")

# Store running processes
processes: Dict[str, Dict[str, Any]] = {}
process_counter = 0
process_lock = threading.Lock()

class RunRequest(BaseModel):
    openfoam_path: Optional[str] = None
    output: Optional[str] = None
    prompt_file: Optional[str] = None  # Path to a prompt file
    prompt: Optional[str] = None       # Direct prompt content
    case: Optional[str] = None         # Case name

class ProcessResponse(BaseModel):
    status: str
    message: str
    process_id: Optional[str] = None

class ProcessStatusResponse(BaseModel):
    status: str
    command: Optional[str] = None
    returncode: Optional[int] = None
    stdout: Optional[str] = None  # Will contain log file contents

class ProcessListItem(BaseModel):
    id: str
    status: str
    command: str
    returncode: Optional[int] = None

class ProcessListResponse(BaseModel):
    processes: List[ProcessListItem]

def monitor_process(pid: str, proc: subprocess.Popen, log_file_path: str):
    # Process has already been started in run_foambench with stdout/stderr redirected to the log file
    # Here we just wait for the process to complete
    proc.wait()
    
    # Update the log file with completion status
    with open(log_file_path, 'a') as log_file:
        log_file.write(f"\n\n=== Process completed at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} with return code {proc.returncode} ===\n")
        
    # Update process info
    with process_lock:
        if pid in processes:
            processes[pid]['status'] = 'completed' if proc.returncode == 0 else 'failed'
            processes[pid]['returncode'] = proc.returncode
            processes[pid]['log_file_path'] = log_file_path

@app.post("/api/run", response_model=ProcessResponse)
async def run_foambench(request: RunRequest, background_tasks: BackgroundTasks):
    """
    Run the foambench_main.py script with the provided parameters.
    """
    global process_counter
    
    # Get default paths with user's home directory
    home_dir = os.path.expanduser("~")
    default_openfoam_path = os.path.join(home_dir, "downloads/OpenFOAM-v2206")
    default_output_path = os.path.join(home_dir, "downloads/Foam-Agent/output")
    default_prompt_path = os.path.join(home_dir, "downloads/Foam-Agent/prompt.txt")
    
    # Validate that only one of prompt or prompt_file is provided
    if request.prompt and request.prompt_file:
        raise HTTPException(
            status_code=400, 
            detail="Only one of 'prompt' or 'prompt_file' can be specified, not both"
        )
    
    if not request.prompt and not request.prompt_file:
        raise HTTPException(
            status_code=400, 
            detail="Either 'prompt' or 'prompt_file' must be specified"
        )
    
    # Extract parameters with defaults
    openfoam_path = request.openfoam_path or default_openfoam_path
    output_path = request.output or default_output_path
    
    # Assign a unique ID to this process first (we need this for all paths)
    with process_lock:
        process_id = str(process_counter)
        process_counter += 1
        
    # Create log directory if it doesn't exist
    log_dir = os.path.join(os.path.expanduser("~"), "downloads/Foam-Agent/log")
    os.makedirs(log_dir, exist_ok=True)
    
    # Function to find the next available ID in the output directory
    def get_next_available_id(directory):
        if not os.path.exists(directory):
            return 1
            
        # List all directories in the output path
        try:
            items = os.listdir(directory)
            max_id = 0
            
            # Find the highest ID used
            for item in items:
                item_path = os.path.join(directory, item)
                if os.path.isdir(item_path):
                    # Try to extract the ID from the directory name (e.g., "1-case" => 1)
                    try:
                        if "-" in item:
                            dir_id = int(item.split("-")[0])
                            max_id = max(max_id, dir_id)
                    except ValueError:
                        # If we can't convert to int, just skip this directory
                        pass
            
            # Return the next available ID
            return max_id + 1
        except Exception as e:
            print(f"Error finding next available ID: {str(e)}")
            return 1
    
    # Get the next available ID
    next_id = get_next_available_id(output_path)
    
    # Determine case name
    raw_case_name = request.case or f"run_{process_id}"
    # Format as {id}-{case_name}
    case_name = f"{next_id}-{raw_case_name}"
    
    # Handle prompt options
    if request.prompt:
        # Use a consistent naming convention for the prompt file
        filename = f"{case_name}_prompt.txt"
        prompt_file_path = os.path.join(log_dir, filename)
        with open(prompt_file_path, "w") as f:
            f.write(request.prompt)
        prompt_path = prompt_file_path
    else:
        # Use the provided prompt file path
        prompt_path = request.prompt_file
    
    # Create a case-specific output directory
    case_output_path = os.path.join(output_path, case_name)
    os.makedirs(case_output_path, exist_ok=True)
    
    # Build the command
    cmd = [
        sys.executable,
        "foambench_main.py",
        "--openfoam_path", openfoam_path,
        "--output", case_output_path,
        "--prompt_path", prompt_path
    ]
    
    # Add case name if provided
    if request.case:
        cmd.extend(["--case", request.case])
    
    # Display the command for debugging
    cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
    print(f"Executing: {cmd_str}")
    
    try:
        # Create output directory if it doesn't exist
        os.makedirs(output_path, exist_ok=True)
        
        # Create log file with timestamp - using case_name for better traceability
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file_path = os.path.join(log_dir, f"{case_name}.log")
        
        # Write initial timestamp and command to the log file
        with open(log_file_path, 'w') as log_file:
            log_file.write(f"=== Process started at {timestamp} ===\n")
            log_file.write(f"Command: {cmd_str}\n\n")
        
        # Open the log file for writing
        with open(log_file_path, 'a') as log_file:
            # Start the process with stdout/stderr directly redirected to the log file
            process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                text=True,
                bufsize=1,  # Line buffered
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
        
        # Register the process
        with process_lock:
            processes[process_id] = {
                'process': process,
                'command': cmd_str,
                'status': 'running',
                'log_file_path': log_file_path,
                'case': request.case
            }
        
        # Start a thread to monitor and log the process output
        threading.Thread(target=monitor_process, args=(process_id, process, log_file_path), daemon=True).start()
        
        return {
            "status": "success",
            "message": "Process started successfully",
            "process_id": process_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start process: {str(e)}")

@app.get("/api/status/{process_id}", response_model=ProcessStatusResponse)
async def get_process_status(process_id: str):
    """
    Get the status of a running or completed process
    """
    with process_lock:
        if process_id not in processes:
            raise HTTPException(status_code=404, detail=f"Process ID {process_id} not found")
        
        process_info = processes[process_id]
        
        response = {
            "status": process_info["status"],
            "command": process_info["command"]
        }
        
        # Add additional details if the process has completed
        if process_info["status"] in ["completed", "failed"]:
            response["returncode"] = process_info.get("returncode")
            
            # Read log file contents if it exists
            log_file_path = process_info.get("log_file_path")
            log_content = ""
            
            if log_file_path and os.path.exists(log_file_path):
                try:
                    with open(log_file_path, 'r') as log_file:
                        log_content = log_file.read()
                except Exception as e:
                    log_content = f"Error reading log file: {str(e)}"
                
                # Limit to 10000 characters
                if len(log_content) > 10000:
                    log_content = log_content[:10000] + "... (truncated, see full log at " + log_file_path + ")"
                
                response["stdout"] = log_content
        
        return response

@app.post("/api/stop/{process_id}", response_model=ProcessResponse)
async def stop_process(process_id: str, background_tasks: BackgroundTasks):
    """
    Stop a running process
    """
    with process_lock:
        if process_id not in processes:
            raise HTTPException(status_code=404, detail=f"Process ID {process_id} not found")
        
        process_info = processes[process_id]
        
        if process_info["status"] != "running":
            raise HTTPException(
                status_code=400, 
                detail=f"Process is not running (current status: {process_info['status']})"
            )
        
        try:
            process_info["process"].terminate()
            
            # Give it a few seconds to terminate gracefully
            def wait_and_kill(pid, proc):
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                
                with process_lock:
                    if pid in processes:
                        processes[pid]["status"] = "stopped"
            
            background_tasks.add_task(wait_and_kill, process_id, process_info["process"])
            
            return {
                "status": "success",
                "message": "Process termination requested"
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to stop process: {str(e)}")

@app.get("/api/list", response_model=ProcessListResponse)
async def list_processes():
    """
    List all processes tracked by the API
    """
    with process_lock:
        result = []
        for pid, info in processes.items():
            result.append({
                "id": pid,
                "status": info["status"],
                "command": info["command"],
                "returncode": info.get("returncode") if info["status"] != "running" else None
            })
        
        return {"processes": result}

if __name__ == '__main__':
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='REST API server for controlling foambench')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', default=8000, type=int, help='Port to bind to')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload')
    
    args = parser.parse_args()
    
    print(f"Starting FastAPI server on {args.host}:{args.port}")
    uvicorn.run("api_server:app", host=args.host, port=args.port, reload=args.reload)
