from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_community.vectorstores import Neo4jVector
import json
import src.connection as connection
from src.prompt.index.community_report_new import BATCH_COMMUNITY_REPORT_PROMPT
from src.prompt.index.extract_graph import GRAPH_EXTRACTION_PROMPT
from src.prompt.index.community_report import COMMUNITY_REPORT_PROMPT
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from neo4j import GraphDatabase
from langchain_core.output_parsers import StrOutputParser
import networkx as nx
import os



#  1. INGESTION
def run_ingestion(yaml_content):
    import time
    t1 = time.time()
    print("[1/3] Running Extraction...")

    prompt = PromptTemplate.from_template(GRAPH_EXTRACTION_PROMPT)
    chain = prompt | connection.llm | StrOutputParser()


    try:
        result_text = chain.invoke({
            "input_text": str(yaml_content),
            "entity_types": "DEVICE,INTERFACE,IP_ADDRESS,PROTOCOL",
            "tuple_delimiter": "|",
            "record_delimiter": "\n",
            "completion_delimiter": "<DONE>"
        })

        with open("log/index/resultindex.txt", "w", encoding="utf-8") as f:
            f.write(result_text)

    except Exception as e:
        print(f"Extraction Failed: {e}")
        return

    entities = []
    relationships = []

    # Tách từng dòng
    lines = result_text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line or line == "<DONE>": continue

        if line.startswith("(") and line.endswith(")"):
            line = line[1:-1]

        parts = line.split("|")

        # Parse Entity: "entity"|name|type|desc
        if len(parts) >= 4 and "entity" in parts[0].lower():
            entities.append({
                "name": parts[1].strip(),
                "type": parts[2].strip(),
                "desc": parts[3].strip()
            })

        # Parse Relationship: "relationship"|src|tgt|desc|strength
        elif len(parts) >= 5 and "relationship" in parts[0].lower():
            relationships.append({
                "source": parts[1].strip(),
                "target": parts[2].strip(),
                "desc": parts[3].strip(),
                "strength": parts[4].strip()
            })

    print(f"   -> Extracted {len(entities)} Entities & {len(relationships)} Relationships.")
    with open("log/index/EntityRelationship.json", "w", encoding="utf-8") as f:
        json.dump(entities, f, ensure_ascii=False, indent=2)
        json.dump(relationships, f, ensure_ascii=False, indent=2)

    # Nạp vào Neo4j
    print("   -> Writing to Neo4j...")
    #connection.graph.query("MATCH (n) DETACH DELETE n")  # Reset DB

    # 1. Tạo Nodes
    for ent in entities:
        # Chuẩn hóa nhãn
        raw_type = ent['type'].upper().strip()
        label = raw_type.replace(" ", "_").replace("{", "").replace("}", "")


        # Gán nhãn chung :Entity và nhãn riêng
        query = f"""
            MERGE (e:Entity {{id: $name}})
            SET e:{label}, e.type = $type, e.desc = $desc
        """
        connection.graph.query(query, {
            "name": ent['name'],
            "type": ent['type'],
            "desc": ent['desc']
        })

    # 2. Tạo Edges
    for rel in relationships:
        connection.graph.query(
            """
            MATCH (a:Entity {id: $src}), (b:Entity {id: $tgt})
            MERGE (a)-[r:CONNECTED_TO]->(b)
            SET r.desc = $desc, 
                r.strength = toInteger($strength)
            """,
            {
                "src": rel['source'],
                "tgt": rel['target'],
                "desc": rel['desc'],
                "strength": rel.get('strength', '1')
            }
        )

    #run_leiden()
    #run_clustering_louvain()
    t2 = time.time()
    print(f"Thời gian extract entities và realtionship: {t2-t1} (s)")


def run_clustering_louvain():
    import time
    t1 = time.time()
    print("[2/3] Running Louvain Algorithm (Client-side)...")

    # 1. Tải Graph từ Neo4j về Python
    data = connection.graph.query("""
        MATCH (s:Entity)-[r:CONNECTED_TO]->(t:Entity)
        RETURN s.id as source, t.id as target
    """)

    if not data:
        print("Graph trống, bỏ qua bước phân cụm.")
        return

    # 2. Dựng đồ thị NetworkX
    G = nx.Graph()
    for row in data:
        G.add_edge(row['source'], row['target'])

    print(f"   -> Loaded Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")

    # 3. Chạy Louvain
    try:
        # Hàm này trả về list các set: [{node1, node2}, {node3, node4}...]
        # resolution=1.0 là mức độ tiêu chuẩn, tăng lên để cụm nhỏ hơn, giảm đi để cụm to hơn
        communities = nx.community.louvain_communities(G, resolution=0, seed=123)

        print(f"   -> Found {len(communities)} communities.")
        communities_list = [list(c) for c in communities]
        with open("log/index/communities.txt", "w", encoding="utf-8") as f:
            f.write(json.dumps(communities_list, ensure_ascii=False, indent=2))

        # 4. Cập nhật communityId ngược lại vào Neo4j
        print("   -> Updating Neo4j...")

        # Reset communityId cũ
        connection.graph.query("MATCH (e:Entity) REMOVE e.communityId")

        # Duyệt và update
        batch_queries = []
        for i, members in enumerate(communities):
            cid = str(i)
            # Chuyển set thành list để gửi vào query
            member_list = list(members)

            # Update batch cho nhanh
            connection.graph.query("""
                UNWIND $members as name
                MATCH (e:Entity {id: name})
                SET e.communityId = $cid
            """, {"members": member_list, "cid": cid})

        # Chuyển sang bước tóm tắt
        run_summarization()

    except Exception as e:
        print(f"Louvain Error: {e}")
        print("Fallback: Gán tất cả vào Community 0")
        connection.graph.query("MATCH (e:Entity) SET e.communityId = '0'")
        run_summarization()


    t2 = time.time()
    print(f"Louvain + sumary time: {t2-t1} (s)")



def run_summarization():
    print("[3/3] Generating Community Reports (Batch Mode)...")

    cids_result = connection.graph.query(
        "MATCH (d:Entity) WHERE d.communityId IS NOT NULL RETURN distinct d.communityId as cid")

    # Chuyển kết quả thành list các ID thực tế
    all_cids = [r['cid'] for r in cids_result if r['cid'] is not None]
    print(f"all_cid:\n {all_cids}")

    if not all_cids:
        print(" -> Không tìm thấy Community nào.")
        return

    BATCH_SIZE = 4
    chunks = [all_cids[i:i + BATCH_SIZE] for i in range(0, len(all_cids), BATCH_SIZE)]
    print(f"   -> Tổng {len(all_cids)} cụm. Chia thành {len(chunks)} đợt xử lý.")

    prompt = PromptTemplate.from_template(BATCH_COMMUNITY_REPORT_PROMPT)
    chain = prompt | connection.llm | JsonOutputParser()
    all_findings = []
    full_reports_data = []

    for i, chunk in enumerate(chunks):
        print(f"   -> Processing Batch {i + 1}/{len(chunks)} (IDs: {chunk})...")

        batch_context_text = ""
        for cid in chunk:
            members = connection.graph.query(
                "MATCH (d:Entity {communityId: $cid}) RETURN d.id, d.type, d.desc",
                {"cid": cid}
            )
            batch_context_text += f"\n--- COMMUNITY ID: {cid} ---\n"
            member_text = "\n".join(
                [f"- [{m.get('d.type', 'Device')}] {m['d.id']}: {m.get('d.desc', '')}" for m in members]
            )
            batch_context_text += member_text + "\n"

        try:
            reports_list = chain.invoke({
                "input_text": batch_context_text
            })
            full_reports_data.extend(reports_list)

            # Kiểm tra xem kết quả có phải là list
            if isinstance(reports_list, dict):
                reports_list = [reports_list]

            for report in reports_list:
                r_id = str(report.get('id'))

                if r_id not in chunk:
                    print(f"Warning: LLM returned unknown ID {r_id}")
                    continue

                connection.graph.query("""
                    MERGE (c:Community {id: $cid})
                    SET c.title = $title, 
                        c.summary = $summary, 
                        c.rating = $rating,
                        c.rating_explanation = $explanation,
                        c.findings = $findings
                    WITH c
                    MATCH (d:Entity {communityId: $cid})
                    MERGE (d)-[:IN_COMMUNITY]->(c)
                """, {
                    "cid": r_id,
                    "title": report.get('title', f"Cluster {r_id}"),
                    "summary": report.get('summary', ''),
                    "rating": report.get('rating', 0),
                    "explanation": report.get('rating_explanation', ''),
                    "findings": json.dumps(report.get('findings', []))
                })

                print(f"      -> Done Cluster {r_id}: {report.get('title')}")

                if report.get('findings'):
                    all_findings.extend(report.get('findings'))

        except Exception as e:
            print(f" Batch Error: {e}")

    os.makedirs("log", exist_ok=True)
    with open("log/index/reportsummary.json", "w", encoding="utf-8") as f:
        json.dump(full_reports_data, f, ensure_ascii=False, indent=2)
    # 4. Tạo Index
    create_indices()


def create_indices():
    try:
        Neo4jVector.from_existing_graph(
            embedding=connection.embeddings,
            url=connection.cfg["NEO4J_URI"],
            username=connection.cfg["NEO4J_USERNAME"],
            password=connection.cfg["NEO4J_PASSWORD"],
            index_name="entity_index",
            node_label="Entity",
            text_node_properties=["id", "desc", "type", "infor"],
            embedding_node_property="embedding"
        )
        print("   -> Entity Index Created.")
    except Exception as e:
        print(f"Index Error: {e}")

    print("Build Complete!")


'''
def run_leiden():
    print("[2/3] Running Leiden Algorithm...")
    try:
        # 1. Dọn dẹp projection cũ (nếu có)
        try:
            connection.graph.query("CALL gds.graph.drop('net_graph', false)")
        except Exception:
            pass

        # 2. Tạo In-Memory Graph (Project)
        connection.graph.query("""
            CALL gds.graph.project(
                'net_graph',
                'Device',
                {CONNECTED_TO: {orientation: 'UNDIRECTED'}}
            )
        """)

        # 3. Chạy thuật toán Leiden & Ghi communityId
        res = connection.graph.query("""
            CALL gds.leiden.write(
                'net_graph',
                {writeProperty: 'communityId'}
            ) YIELD communityCount
        """)

        count = res[0]['communityCount']
        print(f"   -> Found {count} communities.")

        # 4. Giải phóng bộ nhớ
        connection.graph.query("CALL gds.graph.drop('net_graph', false)")

        # Chuyển sang bước tóm tắt
        run_summarization()

    except Exception as e:
        print(f"Leiden Error: {e}")
        print("Gợi ý: Hãy đảm bảo bạn đã cài plugin 'Graph Data Science' (GDS) trong Neo4j.")

'''

'''
if __name__ == '__main__':
    import os
    DATA_FILE_PATH = os.path.join("../data/networkconfig.yml")
    init_connections()
    yaml_content = load_yaml_data()

    if yaml_content:
        run_ingestion(yaml_content)
        run_clustering_louvain()
        '''



