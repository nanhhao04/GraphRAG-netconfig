import os
import json


def extract_project_to_match_format(project_root, repo_name="Graph RAG", branch_name="main"):

    # 1. Thêm 'log' vào danh sách loại bỏ thư mục
    exclude_dirs = {'.git', 'venv', '__pycache__', 'node_modules', '.vscode', '.idea', 'dist', 'build', 'log'}

    # 2. Thêm các đuôi file muốn loại bỏ
    exclude_extensions = {'.pyc', '.pyo', '.pyd'}

    result = {
        "project_id": 1,
        "repo_name": repo_name,
        "repo_info": {
            "description": f"Trích xuất cấu trúc từ thư mục: {repo_name}",
            "path": project_root
        },
        "content": {
            branch_name: {}
        }
    }

    try:
        items = os.listdir(project_root)
        for item in items:
            item_path = os.path.join(project_root, item)

            # Bỏ qua nếu nằm trong danh sách exclude_dirs
            if item in exclude_dirs:
                continue

            # Xử lý THƯ MỤC -> CATEGORY
            if os.path.isdir(item_path):
                category_name = item
                files_in_category = []

                for root, _, filenames in os.walk(item_path):
                    if any(ex in root.split(os.sep) for ex in exclude_dirs):
                        continue

                    for fname in filenames:
                        # 3. Kiểm tra phần mở rộng file
                        if any(fname.endswith(ext) for ext in exclude_extensions):
                            continue

                        rel_path = os.path.relpath(os.path.join(root, fname), item_path)
                        files_in_category.append(rel_path.replace("\\", "/"))

                if files_in_category:
                    result["content"][branch_name][category_name] = sorted(files_in_category)

            # Xử lý FILE ở gốc
            elif os.path.isfile(item_path):
                # Kiểm tra phần mở rộng cho file ở gốc
                if any(item.endswith(ext) for ext in exclude_extensions):
                    continue

                if "root_files" not in result["content"][branch_name]:
                    result["content"][branch_name]["root_files"] = []
                result["content"][branch_name]["root_files"].append(item)

    except Exception as e:
        print(f"Lỗi khi duyệt thư mục: {e}")

    return [result]


def save_matched_json(project_path, output_file):
    repo_name = os.path.basename(os.path.normpath(project_path))
    final_data = extract_project_to_match_format(project_path, repo_name=repo_name)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)

    print(f"--- Đã hoàn thành ---")
    print(f"Project: {repo_name}")
    print(f"Đã loại bỏ: .pyc, log/, __pycache__/")
    print(f"Kết quả lưu tại: {output_file}")


if __name__ == "__main__":
    # Tìm project root (GraphRAG)
    current_file = os.path.abspath(__file__)
    root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
    save_matched_json(root, "../../data/extracted_sample_format.json")