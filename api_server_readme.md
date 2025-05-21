# Foam-Agent API Server

This is a FastAPI-based REST API server to control the execution of foambench_main.py.

## Installation

Install the required dependencies:

```bash
pip install "fastapi[standard]"
```

## Running the Server

Start the API server:

```bash
fastapi dev ./api_server.py
```

## API Endpoints

### Run a Foam-Agent Process

```
POST /api/run
```

Request body:
```json
{
  "openfoam_path": "~/downloads/OpenFOAM-v2206",  // Optional
  "output": "~/downloads/Foam-Agent/output",      // Optional
  "prompt_path": "~/downloads/Foam-Agent/prompt.txt", // Optional
  "prompt": "Your prompt text here"            // Optional - takes precedence over prompt_path
}
```

Response:
```json
{
  "status": "success",
  "message": "Process started successfully",
  "process_id": "0"
}
```

### Check Process Status

```
GET /api/status/{process_id}
```

Response:
```json
{
  "status": "running",   // Can be: "running", "completed", "failed", or "stopped"
  "command": "python foambench_main.py ...",
  "returncode": null,    // Only present if completed or failed
  "stdout": "..."        // Contains log file contents if completed or failed
}
```

### Stop a Process

```
POST /api/stop/{process_id}
```

Response:
```json
{
  "status": "success",
  "message": "Process termination requested"
}
```

### List All Processes

```
GET /api/list
```

Response:
```json
{
  "processes": [
    {
      "id": "0",
      "status": "running",
      "command": "python foambench_main.py ..."
    }
  ]
}
```

## Log Files

The API server saves all process output (stdout and stderr) to log files in the `~/downloads/Foam-Agent/log` directory. Each log file is named with the process ID (e.g., `0.log`, `1.log`, etc.) and includes:

- A timestamp at the beginning showing when the process started
- The full command that was executed
- All output from the process, including both standard output and error output

This allows you to review the complete output of each process, even after it has completed.

## Swagger Documentation

When the server is running, visit:
```
http://localhost:8000/docs
```

For API documentation.
