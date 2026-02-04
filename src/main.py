import sys
import os
from src.connection import init_connections
from src.run_ingestion_rulebased import run_ingestion_test
from src.graph import run_ingestion, run_clustering_louvain, run_ingestion
from src.retrieval import global_search, local_search, router_search,  local_search_semantic
import yaml
from src.eval.eval_ragas import run_eval_pipeline
import json

#DATA_FILE_PATH = os.path.join("data", "networkconfig.yml")
DATA_FILE_PATH = os.path.join("../data/networkconfig.yml")


def load_yaml_data():
    if not os.path.exists(DATA_FILE_PATH):
        print(f"Lỗi: Không tìm thấy file dữ liệu tại '{DATA_FILE_PATH}'")
        return None

    try:
        print(f"Đang đọc file: {DATA_FILE_PATH}...")
        with open(DATA_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                print("Cảnh báo: File rỗng!")
                return None
            return content
    except Exception as e:
        print(f"Lỗi khi đọc file: {e}")
        return None

def load_yaml_data_dict():
    if not os.path.exists(DATA_FILE_PATH):
        print(f"Lỗi: Không tìm thấy file dữ liệu tại '{DATA_FILE_PATH}'")
        return None

    try:
        print(f"Đang đọc file: {DATA_FILE_PATH}...")
        with open(DATA_FILE_PATH, "r", encoding="utf-8") as f:
            docs = list(yaml.safe_load_all(f))

            if not docs:
                print("Cảnh báo: File rỗng!")
                return None

            return docs
    except Exception as e:
        print(f"Lỗi khi đọc file: {e}")
        return None


def main():
    print("GRAPH RAG NETWORK SYSTEM ")
    init_connections()

    while True:
        print("\n--------")
        print("1. Xây dựng Graph (Ingest -> Leiden -> Summarize)")
        print("   (Nguồn: data/networkconfig.yml)")
        print("2.Xây cộng đồng và summary")
        print("3.Global Search (Hỏi tổng quan hệ thống)")
        print("4.Local Search (Hỏi chi tiết thiết bị/Lỗi)")
        print("5.Router search")
        print("6.Ragas")
        print("7.Thoát")
        print("-------")

        choice = input("Chọn chức năng (1-7): ").strip()

        if choice == "1":
            # Đọc dữ liệu từ file
            yaml_content = load_yaml_data()

            if yaml_content:
                #run_ingestion(yaml_content)

                run_ingestion_test(yaml_content)

        elif choice == "2":
            run_clustering_louvain()

        elif choice == "3":
            q = input("\nNhập câu hỏi tổng quan (VD: Hệ thống có bao nhiêu cụm? Tình trạng chung thế nào?): ")
            if q.strip():
                print("\nBot đang suy nghĩ (Global Strategy)...")
                response = global_search(q)
                print(f"\nTRẢ LỜI:\n{response}")

        elif choice == "4":
            q = input("\nNhập câu hỏi chi tiết (VD: Router A kết nối với ai? IP của Switch B?): ")
            if q.strip():
                print("\nBot đang suy nghĩ (Local Strategy)...")
                #response = local_search_semantic(q)
                response = local_search(q)
                print(f"\nTRẢ LỜI:\n{response}")

        elif choice == "5":
            q = input("\nNhập câu hỏi : ")
            if q.strip():
                print("\nBot đang suy nghĩ (Local Strategy)...")
                response = router_search(q)
                print(f"\nTRẢ LỜI:\n{response}")


        elif choice == "6":
            q = input("\nNhập câu hỏi cần đánh giá: ").strip()
            if not q: continue
            print("Nếu có câu trả lời mẫu (Ground Truth), Ragas sẽ chấm thêm:")
            print("Context Precision (Độ chính xác ngữ cảnh) Context Recall (Độ bao phủ ngữ cảnh)")
            ground_truth_input = input("Nhập câu trả lời mẫu (Enter để bỏ qua): ").strip()

            ground_truth = ground_truth_input if ground_truth_input else None

            print("\nBot đang suy nghĩ (Local Strategy)...")
            response = local_search(q)
            print(f"\nTRẢ LỜI:\n{response}")

            print("\n[Ragas] Đang chuẩn bị dữ liệu đánh giá...")
            context_file_path = "log/query/final_context_local.json"

            try:
                with open(context_file_path, "r", encoding="utf-8") as f:
                    full_text = f.read()

                if full_text.strip():
                    context_used = [full_text]
                else:
                    context_used = ["Context rỗng"]

            except Exception as e:
                print(f"Lỗi đọc file context json: {e}")
                context_used = ["Không tìm thấy file log context"]

            run_eval_pipeline(q, response, context_used, ground_truth)

        elif choice == "7":
            print("Thoát!")
            sys.exit()

        else:
            print("Lựa chọn không hợp lệ. Vui lòng chọn lại.")


if __name__ == "__main__":
    if not os.path.exists("data"):
        os.makedirs("data")

    main()