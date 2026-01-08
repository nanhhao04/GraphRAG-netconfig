import os
import yaml
from langchain_community.graphs import Neo4jGraph
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from neo4j import GraphDatabase

# --- 1. KHAI BÁO BIẾN GLOBAL (Mặc định là None) ---
cfg = {}
graph = None
llm = None
embeddings = None
driver = None


def load_config():
    """Tìm và đọc file config.yml"""
    # Lấy đường dẫn thư mục hiện tại của file này (src/)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Tìm file config.yml ở thư mục cha (GraphRAG/)
    config_path = os.path.join(current_dir, "..", "config.yml")

    try:
        with open(config_path, "r") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    except FileNotFoundError:
        print(f"Lỗi: Không tìm thấy file cấu hình tại {config_path}")
        return {}


def init_connections():
    global cfg, graph, llm, embeddings, driver

    # Load cấu hình
    cfg = load_config()
    if not cfg:
        print("Cảnh báo: Config rỗng!")
        return

    # --- KẾT NỐI GEMINI ---
    api_key = cfg.get("GOOGLE_API_KEY")
    if api_key:
        try:
            # Gán giá trị vào biến global 'llm'
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=api_key,
                temperature=0
            )
            # Gán giá trị vào biến global 'embeddings'
            embeddings = GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=api_key
            )
            print("Gemini Connected (LLM Ready)")
        except Exception as e:
            print(f"Lỗi kết nối Gemini: {e}")
            llm = None
    else:
        print("Lỗi: Thiếu GOOGLE_API_KEY trong file config.yml")

    # --- KẾT NỐI NEO4J ---
    uri = cfg.get("NEO4J_URI")
    user = cfg.get("NEO4J_USERNAME")
    pwd = cfg.get("NEO4J_PASSWORD")

    if uri and user and pwd:
        try:
            # Gán giá trị vào biến global 'graph'
            graph = Neo4jGraph(url=uri, username=user, password=pwd)
            # Test kết nối bằng một câu query nhẹ
            graph.query("RETURN 1")
            print("Neo4j Connected (Graph DB Ready)")
        except Exception as e:
            print(f"Lỗi kết nối Neo4j: {e}")
            graph = None
    else:
        print("Cảnh báo: Thiếu thông tin kết nối Neo4j")


# Để test nhanh khi chạy trực tiếp file này
if __name__ == "__main__":
    init_connections()
    print(f"Kiểm tra biến LLM: {type(llm)}")