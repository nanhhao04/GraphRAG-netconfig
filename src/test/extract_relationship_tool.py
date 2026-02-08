import os
import re
import json


def scan_project_imports(project_path, output_json, exclude_dirs=None, exclude_files=None):
    """
    Duyệt toàn bộ file trong project và trích xuất thông tin import.

    :param project_path: Đường dẫn tới thư mục project.
    :param output_json: Tên file JSON kết quả.
    :param exclude_dirs: Danh sách các thư mục cần bỏ qua (ví dụ: ['venv', '.git', '__pycache__']).
    :param exclude_files: Danh sách các file cần bỏ qua (ví dụ: ['setup.py']).
    """
    if exclude_dirs is None:
        exclude_dirs = {'.git', 'venv', '.venv', '__pycache__', 'node_modules', '.idea', '.vscode'}
    if exclude_files is None:
        exclude_files = set()

    import_regex = re.compile(
        r'^\s*(?:import\s+[\w\.,\s]+|from\s+[\w\.]+\s+import\s+[\w\.,\s\(\)\*]+)',
        re.MULTILINE
    )

    project_data = []
    code_content = []

    for root, dirs, files in os.walk(project_path):
        # Loại bỏ các thư mục nằm trong danh sách ngoại lệ
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for file in files:
            if file in exclude_files:
                continue

            # Chỉ quét các file mã nguồn
            if file.endswith(('.py', '.js', '.ts', '.java')):
                file_path = os.path.join(root, file)

                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    code_content.append(content)

                    imports = import_regex.findall(content)
                    imports = [imp.strip() for imp in imports]

                    if imports:
                        project_data.append({
                            "file_name": file,
                            "file_path": os.path.relpath(file_path, project_path),
                            "imports": imports,
                            "content": content,
                        })
                except Exception as e:
                    print(f"Không thể đọc file {file_path}: {e}")

    # Lưu vào file JSON
    try:
        with open(output_json, 'w', encoding='utf-8') as jf:
            json.dump(project_data, jf, ensure_ascii=False, indent=4)
        print(f"Đã lưu thông tin vào {output_json}")
    except Exception as e:
        print(f"Lỗi khi lưu file JSON: {e}")


if __name__ == "__main__":
    # Đường dẫn project hiện tại
    #current_prj = os.getcwd()
    current_file = os.path.abspath(__file__)
    root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))

    scan_project_imports(
        project_path=root,
        output_json="../../data/project_structure.json",
        exclude_dirs={'.git', 'venv', 'log'},
        exclude_files={'__init__.py'}
    )