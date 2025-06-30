from dataclasses import dataclass, field
from typing import List, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
import argparse
from pathlib import Path
from utils import LLMService

from config import Config
from architect_node import architect_node
from input_writer_node import input_writer_node
from runner_node import runner_node
from reviewer_node import reviewer_node
import json

@dataclass
class GraphState:
    user_requirement: str
    config: Config
    case_dir: str = ""
    tutorial: str = ""
    case_name: str = ""
    subtasks: List[str] = field(default_factory=list)
    current_subtask_index: int = 0
    error_command: Optional[str] = None
    error_content: Optional[str] = None
    loop_count: int = 0

def main(user_requirement: str, config: Config):
    # Create the initial state.
    state = GraphState(user_requirement=user_requirement, config=config)
    state.llm_service = LLMService(config)
    
    state.case_stats = json.load(open(f"{state.config.database_path}/raw/openfoam_case_stats.json", "r"))
    
    architect_node(state)
    input_writer_node(state)
    
    max_loop = config.max_loop
    for i in range(max_loop):
        print(f"Loop {i+1}: ")
        runner_response = runner_node(state)
        if runner_response["goto"] == "end":
            break
        
        reviewer_response = reviewer_node(state)
        if reviewer_response["goto"] == "end":
            break
    
    print(f"<loop>{i}</loop>")
    state.llm_service.print_statistics()
        
    print(state)
    
    # # Build the state graph.
    # graph_builder = StateGraph(GraphState)
    # graph_builder.add_node("architect", architect_node)
    # graph_builder.add_node("input_writer", input_writer_node)
    # graph_builder.add_node("runner", runner_node)
    # graph_builder.add_node("reviewer", reviewer_node)
    
    # # Define edges.
    # graph_builder.add_edge(START, "architect")
    # graph_builder.add_edge("architect", "input_writer")
    # graph_builder.add_edge("input_writer", "runner")
    # graph_builder.add_edge("runner", "reviewer")
    # # From reviewer, if an error was fixed, go back to input_writer; otherwise, finish.
    # graph_builder.add_edge("reviewer", "input_writer")
    # graph_builder.add_edge("reviewer", END)
    # # Also, if runner finds no error, we go to END.
    # graph_builder.add_edge("runner", END)
    
    # # Compile and run the graph.
    # graph = graph_builder.compile()


    print("Workflow finished.")

if __name__ == "__main__":
    # python main.py
    parser = argparse.ArgumentParser(
        description="Run the OpenFOAM workflow."
    )
    parser.add_argument(
        "--prompt_path",
        type=str,
        default=f"{Path(__file__).parent.parent}/user_requirement.txt",
        help="User requirement file path for the workflow.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="",
        help="Output directory for the workflow.",
    )
    parser.add_argument(
        "--case",
        type=str,
        default=None,
        help="Case name for the workflow.",
    )
    parser.add_argument(
        "--msh",
        type=str,
        default=None,
        help="Path to MSH file for fluentMeshToFoam",
    )
    
    args = parser.parse_args()
    print(args)
    
    # Initialize configuration.
    config = Config()
    
    # Set the output directory if provided
    if args.output_dir:
        config.run_directory = args.output_dir
        
    # Set the case name if provided
    if args.case:
        config.case_dir = args.case
    elif args.output_dir != "":
        # Only use output_dir for case_dir if case is not provided
        config.case_dir = args.output_dir
        
    # Set the MSH file path if provided
    if args.msh:
        config.msh_file = args.msh
    
    with open(args.prompt_path, 'r') as f:
        user_requirement = f.read()
    
    main(user_requirement, config)
