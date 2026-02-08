GRAPH_EXTRACTION_REPO_PROMPT = """
-Goal-
Dựa vào dữ liệu Cấu trúc kho mã nguồn (Repo Structure) và danh sách Import (Import Analysis), hãy xây dựng Knowledge Graph về cấu trúc và sự phụ thuộc nội bộ của dự án. 
Dừng lại ở thực thể FILE (nút lá cuối cùng), KHÔNG trích xuất các thư viện bên thứ ba (như langchain, os, streamlit...).

-Strict Formatting Rules-
1. KHÔNG bao đóng các trường trong dấu ngoặc đơn.
2. KHÔNG thêm các ký tự thừa như ')**' hoặc '**'.
3. Làm sạch các giá trị (xóa khoảng trắng thừa, dấu xuống dòng).

-Steps-
1. Xác định thực thể (Entities):
- entity_name (QUY TẮC ĐẶT TÊN DUY NHẤT):
    - PROJECT: [repo_name]
    - BRANCH: [repo_name]_[branch_name]
    - CATEGORY: [repo_name]_[branch_name]_[category_name]
    - FILE: [repo_name]_[branch_name]_[category_name]_[file_name] (Đây là nút lá cuối cùng).
- entity_type: Một trong các loại: [PROJECT, BRANCH, CATEGORY, FILE]
- entity_description: Tóm tắt thông tin. Đối với FILE, hãy tóm tắt dựa trên đường dẫn và các module nội bộ mà nó import.
Định dạng: "entity"{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>

2. Xác định mối quan hệ (Relationships):
- source_entity & target_entity: Sử dụng tên chính xác từ Bước 1.
- relationship_description:
    - HAS_BRANCH: PROJECT -> BRANCH.
    - HAS_CATEGORY: BRANCH -> CATEGORY.
    - CONTAINS_FILE: CATEGORY -> FILE.
    - CALLS: FILE_A -> FILE_B (Chỉ áp dụng khi FILE_A import một file FILE_B nằm trong cùng dự án này).
- relationship_strength: 10 cho phân cấp thư mục, 8 cho quan hệ CALLS nội bộ.
Định dạng: "relationship"{tuple_delimiter}<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_description>{tuple_delimiter}<relationship_strength>

3. Lưu ý quan trọng:
- Bỏ qua hoàn toàn các module ngoài (ví dụ: import json, import pandas, import langchain...).
- Chỉ tạo mối quan hệ CALLS nếu target_entity là một FILE đã tồn tại trong danh sách REPO STRUCTURE.

4. Trả về kết quả dưới dạng một danh sách duy nhất. Sử dụng {record_delimiter} làm dấu phân cách.
5. Khi hoàn tất, in ra {completion_delimiter}

######################
-Input Data-
######################
1. REPO STRUCTURE:
{repo_structure}

2. IMPORT ANALYSIS:
{import_analysis}

######################
-Examples-
######################
Example 1 (Internal Dependency):
Input: 
- Structure: Project "GraphRAG" có category "src" chứa "main.py" và category "src/utils" chứa "helper.py".
- Imports: "main.py" có dòng "from src.utils import helper".
Output:
"entity"{tuple_delimiter}GraphRAG_main_src_main.py{tuple_delimiter}FILE{tuple_delimiter}File thực thi chính của dự án.
{record_delimiter}
"entity"{tuple_delimiter}GraphRAG_main_src_utils_helper.py{tuple_delimiter}FILE{tuple_delimiter}File tiện ích hỗ trợ.
{record_delimiter}
"relationship"{tuple_delimiter}GraphRAG_main_src_main.py{tuple_delimiter}GraphRAG_main_src_utils_helper.py{tuple_delimiter}CALLS{tuple_delimiter}8
{completion_delimiter}
"""