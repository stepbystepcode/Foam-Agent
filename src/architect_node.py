# architect_node.py
import os
import re
from utils import save_file, retrieve_faiss, parse_directory_structure
from pydantic import BaseModel, Field
from typing import List
import shutil

class CaseSummaryPydantic(BaseModel):
    case_name: str = Field(description="name of the case")
    case_domain: str = Field(description="domain of the case, case domain must be one of [basic,combustion,compressible,discreteMethods,DNS,electromagnetics,financial,heatTransfer,incompressible,lagrangian,mesh,multiphase,resources,stressAnalysis].")
    case_category: str = Field(description="category of the case")
    case_solver: str = Field(description="solver of the case")


class SubtaskPydantic(BaseModel):
    file_name: str = Field(description="Name of the OpenFOAM input file")
    folder_name: str = Field(description="Name of the folder where the foamfile should be stored")

class OpenFOAMPlanPydantic(BaseModel):
    subtasks: List[SubtaskPydantic] = Field(description="List of subtasks, each with its corresponding file and folder names")


def architect_node(state):
    """
    Architect node: Parse the user requirement to a standard case description,
    finds a similar reference case from the FAISS databases, and splits the work into subtasks.
    Updates state with:
      - case_dir, tutorial, case_name, subtasks.
    """
    config = state.config
    user_requirement = state.user_requirement

    # Step 1: Translate user requirement.
    parse_system_prompt = ("Please transform the following user requirement into a standard case description using a structured format."
                           "The key elements should include case name, case domain, case category, and case solver."
                           f"Note: case domain must be one of {state.case_stats['case_domain']}."
                           f"Note: case category must be one of {state.case_stats['case_category']}."
                           f"Note: case solver must be one of {state.case_stats['case_solver']}."
                           )
    parse_user_prompt = f"User requirement: {user_requirement}."
    
    parse_response = state.llm_service.invoke(parse_user_prompt, parse_system_prompt, pydantic_obj=CaseSummaryPydantic)
    
    state.case_name = parse_response.case_name.replace(" ", "_")
    state.case_domain = parse_response.case_domain
    state.case_category = parse_response.case_category
    state.case_solver = parse_response.case_solver
    
    print(f"Parsed case name: {state.case_name}")
    print(f"Parsed case domain: {state.case_domain}")
    print(f"Parsed case category: {state.case_category}")
    print(f"Parsed case solver: {state.case_solver}")
    
    # Step 2: Determine case directory.
    # Always use config.run_directory as the base directory
    # and add case_dir as a subdirectory
    base_dir = config.run_directory
    
    if config.case_dir != "":
        # Use case_dir as a subdirectory name, not as a full path
        # This ensures it's always under the output directory
        state.case_dir = os.path.join(base_dir, config.case_dir)
    else:
        if config.run_times > 1:
            state.case_dir = os.path.join(base_dir, f"{state.case_name}_{config.run_times}")
        else:
            state.case_dir = os.path.join(base_dir, state.case_name)
    
    if os.path.exists(state.case_dir):
        print(f"Warning: Case directory {state.case_dir} already exists. Overwriting.")
        shutil.rmtree(state.case_dir)
    os.makedirs(state.case_dir)
    
    print(f"Created case directory: {state.case_dir}")
    
    # Handle MSH file if provided
    if hasattr(config, 'msh_file') and config.msh_file and os.path.exists(config.msh_file):
        print(f"Processing MSH file: {config.msh_file}")
        
        # Create system directory if it doesn't exist
        system_dir = os.path.join(state.case_dir, "system")
        os.makedirs(system_dir, exist_ok=True)
        
        # Create a basic controlDict file if it doesn't exist
        control_dict_path = os.path.join(system_dir, "controlDict")
        if not os.path.exists(control_dict_path):
            control_dict_content = """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}

application     simpleFoam;

startFrom       startTime;

startTime       0;

stopAt          endTime;

endTime         500;

deltaT          1;

writeControl    timeStep;

writeInterval   50;

purgeWrite      0;

writeFormat     ascii;

writePrecision  6;

writeCompression off;

timeFormat      general;

timePrecision   6;

runTimeModifiable true;

functions
{
    forceCoeffs
    {
        type            forceCoeffs;
        libs            ("libforces.so");
        patches         ("<patches_to_monitor>");
        rho             rhoInf;
        rhoInf          1.0;
        CofR            (0 0 0);
        pitchAxis       (0 1 0);
        magUInf         1.0;
        lRef            1.0;
        Aref            1.0;
        liftDir         (0 1 0);
        dragDir         (1 0 0);
    }
}
"""
            with open(control_dict_path, 'w') as f:
                f.write(control_dict_content)
            print(f"Created basic controlDict at {control_dict_path}")
        
        # Create mesh directory
        mesh_dir = os.path.join(state.case_dir)
        os.makedirs(mesh_dir, exist_ok=True)
        
        # Copy MSH file to mesh directory
        msh_filename = os.path.basename(config.msh_file)
        dest_msh = os.path.join(mesh_dir, msh_filename)
        shutil.copy2(config.msh_file, dest_msh)
        
        # Run fluentMeshToFoam on the MSH file
        print(f"Running fluentMeshToFoam on {msh_filename}")
        fluent_cmd = f"cd {state.case_dir} && fluentMeshToFoam {msh_filename}"
        print(fluent_cmd)
        fluent_out = os.path.join(mesh_dir, "fluentMeshToFoam.out")
        fluent_err = os.path.join(mesh_dir, "fluentMeshToFoam.err")
        
        # Run the command and check for errors
        os.system(f"{fluent_cmd} > {fluent_out} 2> {fluent_err}")
        
        # Check for errors in fluentMeshToFoam
        if os.path.exists(fluent_err) and os.path.getsize(fluent_err) > 0:
            with open(fluent_err, 'r') as f:
                errors = f.read().strip()
                if errors:
                    print(f"Warning: Errors during fluentMeshToFoam: {errors}")
        
        print("Mesh conversion completed")

    # Step 3: Retrieve a similar reference case from the FAISS databases.
    # Retrieve by case info
    case_info = f"case name: {state.case_name}\ncase domain: {state.case_domain}\ncase category: {state.case_category}\ncase solver: {state.case_solver}"
    
    faiss_structure = retrieve_faiss("openfoam_tutorials_structure", case_info, topk=state.config.searchdocs)
    faiss_structure = faiss_structure[0]['full_content']
    
    # Retrieve by case info + directory structure
    faiss_detailed = retrieve_faiss("openfoam_tutorials_details", faiss_structure, topk=state.config.searchdocs)
    faiss_detailed = faiss_detailed[0]['full_content']
    
    dir_structure = re.search(r"<directory_structure>(.*?)</directory_structure>", faiss_detailed, re.DOTALL).group(1).strip()
    print(f"Retrieved similar case structure: {dir_structure}")
    
    dir_counts = parse_directory_structure(dir_structure)
    dir_counts_str = ',\n'.join([f"There are {count} files in Directory: {directory}" for directory, count in dir_counts.items()])
    print(dir_counts_str)
    
    # Retrieve a reference Allrun script from the FAISS "Allrun" database.
    index_content = f"<index>\ncase name: {state.case_name}\ncase solver: {state.case_solver}</index>\n<directory_structure>{dir_structure}</directory_structure>"
    faiss_allrun = retrieve_faiss("openfoam_allrun_scripts", index_content, topk=state.config.searchdocs)
    allrun_reference = "Similar cases are ordered, with smaller numbers indicating greater similarity. For example, similar_case_1 is more similar than similar_case_2, and similar_case_2 is more similar than similar_case_3.\n"
    for idx, item in enumerate(faiss_allrun):
        allrun_reference += f"<similar_case_{idx + 1}>{item['full_content']}</similar_case_{idx + 1}>\n\n\n"
    
    case_path = os.path.join(state.case_dir, "similar_case.txt")
    
    # TODO update all information to faiss_detailed
    state.tutorial_reference = faiss_detailed
    state.case_path_reference = case_path
    state.dir_structure_reference = dir_structure
    state.case_info = case_info
    state.allrun_reference = allrun_reference
    
    save_file(case_path, f"{faiss_detailed}\n\n\n{allrun_reference}")
        

    # Step 4: Break down the work into smaller, manageable subtasks.
    decompose_system_prompt = (
        "You are an experienced Planner specializing in OpenFOAM projects. "
        "Your task is to break down the following user requirement into a series of smaller, manageable subtasks. "
        "For each subtask, identify the file name of the OpenFOAM input file (foamfile) and the corresponding folder name where it should be stored. "
        "Your final output must strictly follow the JSON schema below and include no additional keys or information:\n\n"
        "```\n"
        "{\n"
        "  \"subtasks\": [\n"
        "    {\n"
        "      \"file_name\": \"<string>\",\n"
        "      \"folder_name\": \"<string>\"\n"
        "    }\n"
        "    // ... more subtasks\n"
        "  ]\n"
        "}\n"
        "```\n\n"
        "Make sure that your output is valid JSON and strictly adheres to the provided schema."
        "Make sure you generate all the necessary files for the user's requirements."
    )

    decompose_user_prompt = (
        f"User Requirement: {user_requirement}\n\n"
        f"Reference Directory Structure (similar case): {dir_structure}\n\n{dir_counts_str}\n\n"        
        "Make sure you generate all the necessary files for the user's requirements."
        "Please generate the output as structured JSON."
    )
    
    decompose_resposne = state.llm_service.invoke(decompose_user_prompt, decompose_system_prompt, pydantic_obj=OpenFOAMPlanPydantic)

    if len(decompose_resposne.subtasks) == 0:
        print("Failed to generate subtasks.")
        raise ValueError("Failed to generate subtasks.")

    print(f"Generated {len(decompose_resposne.subtasks)} subtasks.")

    state.subtasks = decompose_resposne.subtasks

    return {"goto": "input_writer"}
