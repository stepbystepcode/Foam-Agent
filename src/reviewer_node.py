# reviewer_node.py
import os
from utils import save_file, FoamPydantic
from pydantic import BaseModel, Field
from typing import List
import datetime
"""
原有提示词：
  "You are an expert in OpenFOAM simulation and numerical modeling. "
    "Your task is to review the provided error logs and diagnose the underlying issues. "
    "You will be provided with a similar case reference, which is a list of similar cases that are ordered by similarity. You can use this reference to help you understand the user requirement and the error."
    "When an error indicates that a specific keyword is undefined (for example, 'div(phi,(p|rho)) is undefined'), your response must propose a solution that simply defines that exact keyword as shown in the error log. "
    "Do not reinterpret or modify the keyword (e.g., do not treat '|' as 'or'); instead, assume it is meant to be taken literally. "
    "Propose ideas on how to resolve the errors, but do not modify any files directly. "
    "Please do not propose solutions that require modifying any parameters declared in the user requirement, try other approaches instead. Do not ask the user any questions."
    "The user will supply all relevant foam files along with the error logs, and within the logs, you will find both the error content and the corresponding error command indicated by the log file name."

"""
"""
新提示词：
    "You are an expert in OpenFOAM simulation and numerical modeling. "
    "Your task is to review the provided error logs and diagnose the underlying issues. "
    "For boundary condition errors (e.g. 'Cannot find patchField entry for X'), you must first check constant/polyMesh/boundary and verify the boundary is defined in both 0/p and 0/U files. "
    "When a boundary is missing, respond exactly with: 'REQUIRED_ACTION: Add patchField for X to 0/p and 0/U with type Y' where X is the exact boundary name and Y is the type (e.g. zeroGradient for walls, fixedValue for inlets). "
    "Boundary names are case-sensitive and must match exactly across all files. "
    "You will be provided with a similar case reference, which is a list of similar cases that are ordered by similarity. You can use this reference to help you understand the user requirement and the error."
    "When an error indicates that a specific keyword is undefined (for example, 'div(phi,(p|rho)) is undefined'), your response must propose a solution that simply defines that exact keyword as shown in the error log. "
    "Do not reinterpret or modify the keyword (e.g., do not treat '|' as 'or'); instead, assume it is meant to be taken literally. "
    "Propose ideas on how to resolve the errors, but do not modify any files directly. "
    "Please do not propose solutions that require modifying any parameters declared in the user requirement, try other approaches instead. Do not ask the user any questions."
    "The user will supply all relevant foam files along with the error logs, and within the logs, you will find both the error content and the corresponding error command indicated by the log file name."
"""
"""
第三次修改的提示词：
    "You are an expert in OpenFOAM simulation and numerical modeling. "
    "Your task is to review the provided error logs and diagnose the underlying issues. "
    "For boundary condition errors (e.g. 'Cannot find patchField entry for X'), you must first check constant/polyMesh/boundary and verify the boundary is defined in  0/p, 0/U, 0/k, 0/epsilon and 0/nut files. "
    "When a boundary is missing, respond exactly with: 'REQUIRED_ACTION: Add patchField for X to 0/p, 0/U, 0/k, 0/epsilon and 0/nut with type Y' where X is the exact boundary name and Y is the type (e.g. zeroGradient for walls, fixedValue for inlets). "
    "Boundary names are case-sensitive and must match exactly across all files. "
    "You will be provided with a similar case reference, which is a list of similar cases that are ordered by similarity. You can use this reference to help you understand the user requirement and the error."
    "When an error indicates that a specific keyword is undefined (for example, 'div(phi,(p|rho)) is undefined'), your response must propose a solution that simply defines that exact keyword as shown in the error log. "
    "Do not reinterpret or modify the keyword (e.g., do not treat '|' as 'or'); instead, assume it is meant to be taken literally. "
    "Propose ideas on how to resolve the errors, but do not modify any files directly. "
    "Please do not propose solutions that require modifying any parameters declared in the user requirement, try other approaches instead. Do not ask the user any questions."
    "The user will supply all relevant foam files along with the error logs, and within the logs, you will find both the error content and the corresponding error command indicated by the log file name."


"""
# 以下是新的提示词
REVIEWER_SYSTEM_PROMPT = (
    "You are an expert in OpenFOAM simulation and numerical modeling. "
    "Your task is to review the provided error logs and diagnose the underlying issues. "
    "For boundary condition errors (e.g. 'Cannot find patchField entry for X'), you must first check constant/polyMesh/boundary and verify the boundary is defined in  0/p, 0/U, 0/k, 0/epsilon and 0/nut files simultaneously. "
    "When a boundary is missing, respond exactly with: 'REQUIRED_ACTION: Add patchField for X to 0/p, 0/U, 0/k, 0/epsilon and 0/nut with type Y' where X is the exact boundary name and Y is the type (e.g. zeroGradient for walls, fixedValue for inlets). "
    "Boundary names are case-sensitive and must match exactly across all files. "
    "You will be provided with a similar case reference, which is a list of similar cases that are ordered by similarity. You can use this reference to help you understand the user requirement and the error."
    "When an error indicates that a specific keyword is undefined (for example, 'div(phi,(p|rho)) is undefined'), your response must propose a solution that simply defines that exact keyword as shown in the error log. "
    "Do not reinterpret or modify the keyword (e.g., do not treat '|' as 'or'); instead, assume it is meant to be taken literally. "
    "Propose ideas on how to resolve the errors, but do not modify any files directly. "
    "Please do not propose solutions that require modifying any parameters declared in the user requirement, try other approaches instead. Do not ask the user any questions."
    "The user will supply all relevant foam files along with the error logs, and within the logs, you will find both the error content and the corresponding error command indicated by the log file name."

)

REWRITE_SYSTEM_PROMPT = (
    "You are an expert in OpenFOAM simulation and numerical modeling. "
    "Your task is to modify and rewrite the necessary OpenFOAM files to fix the reported error. "
    "Please do not propose solutions that require modifying any parameters declared in the user requirement, try other approaches instead."
    "The user will provide the error content, error command, reviewer's suggestions, and all relevant foam files. "
    "Only return files that require rewriting, modification, or addition; do not include files that remain unchanged. "
    "Return the complete, corrected file contents in the following JSON format: "
    "list of foamfile: [{file_name: 'file_name', folder_name: 'folder_name', content: 'content'}]. "
    "Ensure your response includes only the modified file content with no extra text, as it will be parsed using Pydantic."
)


def save_to_txt(content, file_prefix, folder="output25"):
    """将内容保存到txt文件，文件名包含时间戳"""
    # 创建文件夹
    if not os.path.exists(folder):
        os.makedirs(folder)

    # 生成带时间戳的文件名

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{file_prefix}_{timestamp}.txt"
    file_path = os.path.join(folder, file_name)

    # 写入文件
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(str(content))

    print(f"已保存至: {file_path}")

def reviewer_node(state):
    """
    Reviewer node: Reviews the error logs and determines if the error
    is related to the input file. 
    """
    config = state.config
    
    print(f"============================== Reviewer Analysis ==============================")
    if len(state.error_logs) == 0:
        print("No error to review.")
        return {"goto": "end"}
    
    # Analysis the reason and give the method to fix the error.
    if hasattr(state, "history_text") and state.history_text:
        # <similar_case_reference>:相似案例参考，帮助LLM理解问题
        # <foamfiles> 当前OpenFOAM文件结构
        # <current_error_logs>: 错误日志内容
        # <history>: 历史分析记录
        # <user_requirement>:用户需求
        """
        相似参考案例包含在了每一次请求之中,是否仅仅第一次提交给他既可以，或者每个几次提交一下
        相似案例很长很长很长很长
        """
        """
        f"{chr(10).join(state.history_text)}\n",history在后期也会很长，考虑删掉
        f"<similar_case_reference>{state.tutorial_reference}</similar_case_reference>\n"仅第一次审查送给大模型，后边几次考虑删掉
        原版
        reviewer_user_prompt = (
            f"<similar_case_reference>{state.tutorial_reference}</similar_case_reference>\n"
            f"<foamfiles>{str(state.foamfiles)}</foamfiles>\n"
            f"<current_error_logs>{state.error_logs}</current_error_logs>\n"
            f"<history>\n"
            f"{chr(10).join(state.history_text)}\n"
            f"</history>\n\n"
            f"<user_requirement>{state.user_requirement}</user_requirement>\n\n"
            f"I have modified the files according to your previous suggestions. If the error persists, please provide further guidance. Make sure your suggestions adhere to user requirements and do not contradict it. Also, please consider the previous attempts and try a different approach."
        )
        """
        reviewer_user_prompt = (
            f"<similar_case_reference>For the similar case reference, please refer to the one previously provided to you. It will not be repeated here.</similar_case_reference>\n"
            f"<foamfiles>For the foamfiles, please refer to the one previously provided to you. It will not be repeated here.</foamfiles>\n"
            f"<current_error_logs>{state.error_logs}</current_error_logs>\n"
            f"<user_requirement>For the user_requirement, please refer to the one previously provided to you. It will not be repeated here.</user_requirement>\n\n"
            f"I have modified the files according to your previous suggestions. If the error persists, please provide further guidance. Make sure your suggestions adhere to user requirements and do not contradict it. Also, please consider the previous attempts and try a different approach."
        )
        '''
        print("将similar_case_reference(相似参考案例) 送入大模型")
        print(state.tutorial_reference)

        print("将foamfiles(文件结构) 送入大模型")
        print(state.foamfiles)

        print("将当前的错误日志 送入大模型")
        print(state.error_logs)

        print("将历史记录 送入大模型")
        print(state.history_text)
        '''
        # 保存到文件
        save_to_txt(state.tutorial_reference, "similar_case_reference")
        save_to_txt(state.foamfiles, "foamfiles")
        save_to_txt(state.error_logs, "current_error_logs")
        save_to_txt(state.history_text, "history_text")

    else:
        """
        这里是第一次审查，还没有历史记录
        这里保留similar_case_reference
        """
        reviewer_user_prompt = (
            f"<similar_case_reference>{state.tutorial_reference}</similar_case_reference>\n"
            f"<foamfiles>{str(state.foamfiles)}</foamfiles>\n"
            f"<error_logs>{state.error_logs}</error_logs>\n"
            f"<user_requirement>{state.user_requirement}</user_requirement>\n"
            "Please review the error logs and provide guidance on how to resolve the reported errors. Make sure your suggestions adhere to user requirements and do not contradict it."
        )

    
    review_response = state.llm_service.invoke(reviewer_user_prompt, REVIEWER_SYSTEM_PROMPT)
    review_content = review_response
    
    # Initialize history_text if it doesn't exist
    if not hasattr(state, "history_text"):
        state.history_text = []
        
    # Add current attempt to history
    current_attempt = [
        f"<Attempt {len(state.history_text)//4 + 1}>\n"
        f"<Error_Logs>\n{state.error_logs}\n</Error_Logs>",
        f"<Review_Analysis>\n{review_content}\n</Review_Analysis>",
        f"</Attempt>\n"  # Closing tag for Attempt with empty line
    ]
    # 这里的历史记录会随着迭代次数的增加会不断变长
    state.history_text.extend(current_attempt)
    
    
    print(review_content)

    # Return the revised foamfile content.
    rewrite_user_prompt = (
        f"<foamfiles>{str(state.foamfiles)}</foamfiles>\n"
        f"<error_logs>{state.error_logs}</error_logs>\n"
        f"<reviewer_analysis>{review_content}</reviewer_analysis>\n\n"
        f"<user_requirement>{state.user_requirement}</user_requirement>\n\n"
        "Please update the relevant OpenFOAM files to resolve the reported errors, ensuring that all modifications strictly adhere to the specified formats. Ensure all modifications adhere to user requirement."
    )
    rewrite_response = state.llm_service.invoke(rewrite_user_prompt, REWRITE_SYSTEM_PROMPT, pydantic_obj=FoamPydantic)
    
    # Save the modified files.
    print(f"============================== Rewrite ==============================")
    for foamfile in rewrite_response.list_foamfile:
        print(f"Modified the file: {foamfile.file_name} in folder: {foamfile.folder_name}")
        file_path = os.path.join(state.case_dir, foamfile.folder_name, foamfile.file_name)
        save_file(file_path, foamfile.content)
        
        # Update state
        if foamfile.folder_name not in state.dir_structure:
            state.dir_structure[foamfile.folder_name] = []
        if foamfile.file_name not in state.dir_structure[foamfile.folder_name]:
            state.dir_structure[foamfile.folder_name].append(foamfile.file_name)
        
        for f in state.foamfiles.list_foamfile:
            if f.folder_name == foamfile.folder_name and f.file_name == foamfile.file_name:
                state.foamfiles.list_foamfile.remove(f)
                break
            
        state.foamfiles.list_foamfile.append(foamfile)
    
    return {"goto": "runner"}
