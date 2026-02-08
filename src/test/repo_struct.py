from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_community.vectorstores import Neo4jVector
import json
import src.connection as connection
from src.prompt.index.community_report_new import BATCH_COMMUNITY_REPORT_PROMPT
from src.prompt.index.extract_graph import GRAPH_EXTRACTION_PROMPT
from src.prompt.index.extract_graph_code_repo import GRAPH_EXTRACTION_REPO_PROMPT
from src.prompt.index.community_report import COMMUNITY_REPORT_PROMPT
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from neo4j import GraphDatabase

from langchain_core.output_parsers import StrOutputParser
import networkx as nx
import os


def run_ingestion_for_repo_struct(repo_structure_data, import_analysis_data):  # Đổi tên tham số cho đúng bản chất JSON
    import time
    t1 = time.time()
    print("[1/3] Running Extraction...")

    # Cấu hình cụ thể dấu phân cách
    T_DELIM = "|"
    R_DELIM = "##"  # Dùng ký tự đặc biệt để tránh lẫn với dấu xuống dòng trong description
    C_DELIM = "<DONE>"

    prompt = PromptTemplate.from_template(GRAPH_EXTRACTION_REPO_PROMPT)
    chain = prompt | connection.llm | StrOutputParser()

    try:
        result_text = chain.invoke({
            "import_analysis": json.dumps(import_analysis_data, indent=2, ensure_ascii=False),
            "repo_structure": json.dumps(repo_structure_data, indent=2, ensure_ascii=False),
            "entity_types": "PROJECT, BRANCH, CATEGORY, FILE",
            "tuple_delimiter": T_DELIM,
            "record_delimiter": R_DELIM,
            "completion_delimiter": C_DELIM
        })

        # Lưu log để debug
        os.makedirs("log/index", exist_ok=True)
        with open("log/index/resultindex.txt", "w", encoding="utf-8") as f:
            f.write(result_text)

    except Exception as e:
        print(f"Extraction Failed: {e}")
        return

    entities = []
    relationships = []

    # Tách theo Record Delimiter đã định nghĩa
    records = result_text.strip().split(R_DELIM)

    for record in records:
        record = record.strip()
        if not record or C_DELIM in record: continue

        # Xử lý dọn dẹp dấu ngoặc kép hoặc ngoặc đơn thừa nếu LLM tự ý thêm vào
        record = record.strip('() "')

        parts = record.split(T_DELIM)

        # Parse Entity: "entity"|name|type|desc
        if "entity" in parts[0].lower() and len(parts) >= 4:
            entities.append({
                "name": parts[1].strip(),
                "type": parts[2].strip(),
                "desc": parts[3].strip()
            })

        # Parse Relationship: "relationship"|src|tgt|desc|strength
        elif "relationship" in parts[0].lower() and len(parts) >= 5:
            # Ép kiểu strength về số, mặc định là 1 nếu lỗi
            try:
                strength = int(parts[4].strip())
            except:
                strength = 1

            relationships.append({
                "source": parts[1].strip(),
                "target": parts[2].strip(),
                "desc": parts[3].strip(),
                "strength": strength
            })

    print(f"   -> Extracted {len(entities)} Entities & {len(relationships)} Relationships.")

    # Lưu JSON hợp lệ
    with open("log/index/EntityRelationship.json", "w", encoding="utf-8") as f:
        json.dump({"entities": entities, "relationships": relationships}, f, ensure_ascii=False, indent=2)

    # Nạp vào Neo4j
    print("   -> Writing to Neo4j...")

    for ent in entities:
        # Làm sạch label: Xóa khoảng trắng, ký tự đặc biệt để làm Label Neo4j
        label = ent['type'].upper().replace(" ", "_").strip()

        query = f"""
            MERGE (e:Entity {{id: $name}})
            SET e:{label}, e.type = $type, e.desc = $desc
        """
        connection.graph.query(query, {
            "name": ent['name'],
            "type": ent['type'],
            "desc": ent['desc']
        })

    for rel in relationships:
        connection.graph.query(
            """
            MATCH (a:Entity {id: $src}), (b:Entity {id: $tgt})
            MERGE (a)-[r:CONNECTED_TO]->(b)
            SET r.desc = $desc, 
                r.strength = $strength
            """,
            {
                "src": rel['source'],
                "tgt": rel['target'],
                "desc": rel['desc'],
                "strength": rel['strength']
            }
        )

    t2 = time.time()
    print(f"Hoàn thành! Tổng thời gian: {round(t2 - t1, 2)} (s)")