import json
import random
import time
from collections import defaultdict

import tiktoken
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_community.vectorstores import Neo4jVector
import src.connection as connection

from src.prompt.query.global_search_map_system_prompt import MAP_SYSTEM_PROMPT
from src.prompt.query.global_search_reduce_system_prompt import REDUCE_SYSTEM_PROMPT
from src.prompt.query.local_search_system_prompt import LOCAL_SEARCH_SYSTEM_PROMPT
from src.prompt.query.router_search import ROUTER_SYSTEM_PROMPT


def count_tokens(text):
    try:
        encoding = tiktoken.get_encoding("cl100k_base") # Encoding chuẩn của GPT-4
        return len(encoding.encode(text))
    except:
        # Fallback nếu chưa cài tiktoken: ước lượng 1 token ~ 4 ký tự
        return len(text) // 4



def global_search(question):
    print("GLOBAL SEARCH MODE (Map-Reduce Strategy)")
    t1 = time.time()

# MAP
    try:
        communities = connection.graph.query("""
            MATCH (c:Community) 
            RETURN c.id as id, c.title as title, c.summary as summary, c.rating as rating
        """)
    except Exception as e:
        return f"Lỗi truy vấn Neo4j: {e}"

    if not communities:
        return "Chưa có dữ liệu Community. Hãy chạy Ingestion trước."

    random.shuffle(communities)  # Xáo trộn ngẫu nhiên

    CHUNK_SIZE = 5
    chunks = [communities[i:i + CHUNK_SIZE] for i in range(0, len(communities), CHUNK_SIZE)]
    print(f" Đã chia {len(communities)} communities thành {len(chunks)} chunks để xử lý.")

    map_chain = PromptTemplate.from_template(MAP_SYSTEM_PROMPT) | connection.llm | JsonOutputParser()
    all_points = []
    global_search_report = []

    for i, chunk in enumerate(chunks):
        chunk_context = ""
        for c in chunk:
            chunk_context += f"\n---\nCommunity ID: {c['id']}\nTitle: {c['title']}\nSummary: {c['summary']}\n"

        try:
            # AI đọc chunk và trả về JSON chứa các points kèm score
            res = map_chain.invoke({"question": question,
                                    "context_data": chunk_context,
                                    "response_type": "JSON list of points",
                                    "max_length": "2000"
                                    })
            global_search_report.append(res)

            if res.get('points'):
                for p in res['points']:
                    # Nội dung + Điểm số
                    all_points.append({
                        "description": p.get('description', ''),
                        "score": p.get('score', 0)
                    })

        except Exception as e:
            print(f"Lỗi xử lý Chunk {i}: {e}")
            continue

    if not all_points:
        return "Không tìm thấy thông tin phù hợp trong hệ thống."

    with open("log/query/globalsearch.json", "w", encoding="utf-8") as f:
        json.dump(global_search_report, f, ensure_ascii=False, indent=2)

    all_points.sort(key=lambda x: x['score'], reverse=True)
    top_points = all_points[:50]
    with open("log/query/top_points.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(top_points, ensure_ascii=False, indent=2))

    formatted_report = "\n".join([f"- [Score: {p['score']}] {p['description']}" for p in top_points])
    with open("log/query/formatted_report_map.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(formatted_report, ensure_ascii=False, indent=2))

    print(f"   -> Tổng hợp {len(top_points)}/{len(all_points)} thông tin quan trọng nhất (Top Scores).")

# REDUCE
    reduce_chain = PromptTemplate.from_template(REDUCE_SYSTEM_PROMPT) | connection.llm | StrOutputParser()
    final_answer = reduce_chain.invoke({
        "question": question,
        "report_data": formatted_report,
        "response_type": "General Text Analysis",
        "max_length": "4000"
    })
    t2 = time.time()
    print(f"Thời gian global search: {t2-t1} (s)")

    return final_answer


def local_search(question):
    print("LOCAL SEARCH MODE (Top-K Nodes + Top-K Relations Strategy)...")
    t1 = time.time()

    SEARCH_K = 5
    TOP_RELATIONS = 10
    HOP1_DECAY = 1.0
    HOP2_DECAY = 0.5

    # 1. VECTOR SEARCH
    try:
        vector_store = Neo4jVector.from_existing_index(
            embedding=connection.embeddings,
            url=connection.cfg["NEO4J_URI"],
            username=connection.cfg["NEO4J_USERNAME"],
            password=connection.cfg["NEO4J_PASSWORD"],
            index_name="entity_index",
            text_node_property="id"
        )
        docs_with_score = vector_store.similarity_search_with_score(question, k=SEARCH_K)
        with open("log/query/anchor_local.txt", "w", encoding="utf-8") as f:
            for doc, score in docs_with_score:
                f.write(f"SCORE: {score}\n")
                f.write(doc.page_content + "\n")
                f.write(str(doc.metadata) + "\n")
                f.write("-" * 50 + "\n")

    except Exception as e:
        return f"Lỗi Vector Index: {e}"

    if not docs_with_score:
        return "Không tìm thấy thiết bị nào liên quan."

    print(f" -> Tìm thấy {len(docs_with_score)} Anchor Nodes.")

    # XỬ LÝ ANCHOR INFO & TRAVERSAL
    anchor_infos = []
    all_relationships = []
    processed_rels = set()

    for doc, score in docs_with_score:
        dev_id = doc.page_content.strip()
        if dev_id == "UNKNOWN": continue

        # a. Lưu thông tin Anchor
        node_desc = doc.metadata.get('desc', 'No description')
        node_type = doc.metadata.get('type', 'Entity')
        anchor_text = f"Node: {dev_id} (Type: {node_type}). Info: {node_desc}"
        anchor_infos.append(anchor_text)

        # b. Traversal Query (2 Hops)
        # Quét Hop 1 và Hop 2 và Loại 'IN_COMMUNITY'
        # UNION để gộp 2 truy vấn + bỏ lặp
        traversal_query = """
            // Hop 1
            MATCH (src:Entity {id: $id})-[r1]-(n1:Entity)
            WHERE type(r1) <> 'IN_COMMUNITY'
            RETURN 
                src.id as src, src.type as src_type,
                type(r1) as rel, r1.desc as rel_desc,
                n1.id as tgt, n1.type as tgt_type, n1.desc as tgt_desc,
                1 as hops

            UNION

            // Hop 2
            MATCH (src:Entity {id: $id})-[r1]-(n1:Entity)-[r2]-(n2:Entity)
            WHERE type(r1) <> 'IN_COMMUNITY' AND type(r2) <> 'IN_COMMUNITY'
            RETURN 
                n1.id as src, n1.type as src_type,
                type(r2) as rel, r2.desc as rel_desc,
                n2.id as tgt, n2.type as tgt_type, n2.desc as tgt_desc,
                2 as hops
        """

        paths = connection.graph.query(traversal_query, {"id": dev_id})
        with open("log/query/query_traversal_local.txt", "a", encoding="utf-8") as f:
            header = f"\n{'=' * 20} Traversal for: {dev_id} (Score: {score:.4f}) {'=' * 20}\n"
            f.write(header)

        for p in paths:
            # (Sorted tuple để A-B và B-A là một)
            rel_key = tuple(sorted([p['src'], p['tgt']])) + (p['rel'],)

            if rel_key in processed_rels:
                continue
            processed_rels.add(rel_key)

            # Tính điểm cho Relationship này
            decay = HOP1_DECAY if p['hops'] == 1 else HOP2_DECAY
            rel_score = score * decay

            rel_desc_str = f" ({p['rel_desc']})" if p['rel_desc'] else ""
            tgt_desc_str = f" ({p['tgt_desc']})" if p['tgt_desc'] else ""

            # Format: [Type] Source --[RELATION (desc)]--> [Type] Target (desc)
            semantic_text = (
                f"[{p['src_type']}] {p['src']} "
                f"--[{p['rel']}{rel_desc_str}]--> "
                f"[{p['tgt_type']}] {p['tgt']}{tgt_desc_str}"
            )

            all_relationships.append({
                "text": semantic_text,
                "score": rel_score,
                "hops": p['hops']
            })

    # RANKING & PRUNING
    all_relationships.sort(key=lambda x: x['score'], reverse=True)

    top_relations = all_relationships[:TOP_RELATIONS]

    print(f"   -> Thu thập {len(all_relationships)} kết nối. Lọc lấy Top {len(top_relations)}.")

    # CONTEXT CONSTRUCTION
    context_parts = []
    context_parts.append("PRIMARY ANCHOR NODES (Top 5 Matches)")
    context_parts.extend(anchor_infos)

    context_parts.append(f"\nTOP {len(top_relations)} RELEVANT CONNECTIONS")
    for rel in top_relations:
        context_parts.append(f"- {rel['text']}")

    final_context_text = "\n".join(context_parts)

    try:
        with open("log/query/final_context_local.json", "w", encoding="utf-8") as f:
            json.dump({
                "llm_context": context_parts
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi ghi log context: {e}")

# LLM GENERATION
    chain = PromptTemplate.from_template(LOCAL_SEARCH_SYSTEM_PROMPT) | connection.llm | StrOutputParser()
    t2 = time.time()
    print(f"Thời gian local search: {t2 - t1:.2f}s")

    return chain.invoke({
        "question": question,
        "context_data": final_context_text
    })


def local_search_semantic(question):
    print("LOCAL SEARCH MODE (Semantic + Cleaning Strategy)...")
    t1 = time.time()

    # Cấu hình
    SEARCH_K = 5
    GRAPH_LIMIT = 200

    # 1. VECTOR SEARCH
    try:
        vector_store = Neo4jVector.from_existing_index(
            embedding=connection.embeddings,
            url=connection.cfg["NEO4J_URI"],
            username=connection.cfg["NEO4J_USERNAME"],
            password=connection.cfg["NEO4J_PASSWORD"],
            index_name="entity_index",
            text_node_property="id"
        )
        docs_with_score = vector_store.similarity_search_with_score(question, k=SEARCH_K)
        with open("log/query/anchor_local.txt", "w", encoding="utf-8") as f:
            for doc, score in docs_with_score:
                f.write(f"SCORE: {score}\n")
                f.write(doc.page_content + "\n")
                f.write(str(doc.metadata) + "\n")
                f.write("-" * 50 + "\n")

    except Exception as e:
        return f"Lỗi Vector Index: {e}"

    if not docs_with_score: return "Không tìm thấy thiết bị nào liên quan."

    # 2. DATA FETCHING (2-HOPS)
    traversal_query = """
        MATCH (anchor:Entity {id: $id})-[r1]-(n1:Entity)
        WHERE type(r1) <> 'IN_COMMUNITY'
        RETURN 
            anchor.id as src_id, anchor.type as src_type, anchor.desc as src_desc,
            type(r1) as rel_type, r1.desc as rel_desc,
            n1.id as tgt_id, n1.type as tgt_type, n1.desc as tgt_desc

        UNION

        MATCH (anchor:Entity {id: $id})-[r1]-(n1:Entity)-[r2]-(n2:Entity)
        WHERE type(r1) <> 'IN_COMMUNITY' AND type(r2) <> 'IN_COMMUNITY'
        RETURN 
            n1.id as src_id, n1.type as src_type, n1.desc as src_desc,
            type(r2) as rel_type, r2.desc as rel_desc,
            n2.id as tgt_id, n2.type as tgt_type, n2.desc as tgt_desc
        LIMIT $limit
    """

    # Cấu trúc dữ liệu (Sử dụng Set cho IP để tự khử trùng lặp)
    devices_map = defaultdict(lambda: {
        "desc": "",
        "interfaces": defaultdict(lambda: {"ip": set(), "desc": ""}),
        "routes": set()
    })

    # Map để trace ngược từ Interface về Device
    interface_parent_map = {}
    node_scores = {}

    def clean_text(text):
        if not text: return ""
        return text.replace(")**", "").strip()

    raw_rows = []

    # Fetch Data
    for doc, score in docs_with_score:
        dev_id = doc.page_content.strip()
        if dev_id == "UNKNOWN": continue

        node_scores[dev_id] = max(node_scores.get(dev_id, 0), score)

        try:
            results = connection.graph.query(traversal_query, {"id": dev_id, "limit": GRAPH_LIMIT})
            with open("log/query/query_traversal_local.txt", "a", encoding="utf-8") as f:
                header = f"\n{'=' * 20} Traversal for: {dev_id} (Score: {score:.4f}) {'=' * 20}\n"
                f.write(header)

                if results:
                    log_content = json.dumps(results, ensure_ascii=False, indent=2)
                    f.write(log_content)
                else:
                    f.write("-> [WARN] No neighbors found in Graph (Empty Result).\n")

                f.write("\n" + "-" * 60 + "\n")

            raw_rows.extend(results)
            #print(f"CHECK: raw_rows: {len(raw_rows)}")
        except:
            continue

    # 3. GOM NHÓM & LÀM SẠCH

    # PASS 1: Xây khung Device - Interface
    for row in raw_rows:
        src_id, src_type = row['src_id'], row['src_type']
        tgt_id, tgt_type = row['tgt_id'], row['tgt_type']

        # Logic: Chỉ map Interface vào Device nếu ID Interface chứa ID Device
        # Hoặc chấp nhận map lỏng lẻo nhưng phải cẩn thận

        if src_type == 'DEVICE' and tgt_type in ['INTERFACE', 'BOND', 'VLAN', 'BRIDGE']:
            devices_map[src_id]['desc'] = clean_text(row['src_desc'])
            devices_map[src_id]['interfaces'][tgt_id]['desc'] = clean_text(row['tgt_desc'])
            interface_parent_map[tgt_id] = src_id  # Mapping Interface -> Device

        elif tgt_type == 'DEVICE' and src_type in ['INTERFACE', 'BOND', 'VLAN', 'BRIDGE']:
            devices_map[tgt_id]['desc'] = clean_text(row['tgt_desc'])
            devices_map[tgt_id]['interfaces'][src_id]['desc'] = clean_text(row['src_desc'])
            interface_parent_map[src_id] = tgt_id

    # PASS 2: Gắn IP và Route
    for row in raw_rows:
        src_id, src_type = row['src_id'], row['src_type']
        tgt_id, tgt_type = row['tgt_id'], row['tgt_type']
        rel = row.get('rel_desc') if row.get('rel_desc') else row['rel_type']

        # Gắn IP (Dùng Set để add, tự động loại trùng)
        if src_type == 'IP_ADDRESS' and tgt_id in interface_parent_map:
            devices_map[interface_parent_map[tgt_id]]['interfaces'][tgt_id]['ip'].add(clean_text(src_id))
        elif tgt_type == 'IP_ADDRESS' and src_id in interface_parent_map:
            devices_map[interface_parent_map[src_id]]['interfaces'][src_id]['ip'].add(clean_text(tgt_id))

        # Gắn Routes
        if src_type == 'DEVICE' and 'ROUTE' in rel.upper():
            devices_map[src_id]['routes'].add(f"To {clean_text(tgt_id)} via {rel}")
        elif tgt_type == 'DEVICE' and 'ROUTE' in rel.upper():
            devices_map[tgt_id]['routes'].add(f"To {clean_text(src_id)} via {rel}")

    # 4. RENDER TEXT
    context_lines = []
    sorted_devs = sorted(devices_map.keys(), key=lambda k: node_scores.get(k, 0), reverse=True)


    context_lines.append("=== DEVICE CONFIGURATIONS ===")

    for dev_id in sorted_devs:
        data = devices_map[dev_id]
        if not data['interfaces'] and not data['routes']: continue

        context_lines.append(f"### DEVICE: {dev_id}")

        short_desc = data['desc'].split("Configuration includes")[0].strip()
        context_lines.append(f"  Role: {short_desc}")

        if data['interfaces']:
            context_lines.append(f"  INTERFACES:")
            for iface in sorted(data['interfaces'].keys()):
                iface_data = data['interfaces'][iface]

                # Convert set IP back to list & sort
                ips = sorted(list(iface_data['ip']))
                ip_str = f" [IPs: {', '.join(ips)}]" if ips else ""

                # Extract Attributes ngắn gọn
                attrs = []
                desc_lower = iface_data['desc'].lower()
                if 'mtu' in desc_lower: attrs.append("MTU:9000")
                if 'bond' in desc_lower: attrs.append("Type:Bond")
                attr_str = f" ({', '.join(attrs)})" if attrs else ""

                context_lines.append(f"    - {iface}{ip_str}{attr_str}")

        if data['routes']:
            context_lines.append(f"  ROUTING TABLE:")
            for r in sorted(list(data['routes'])):
                context_lines.append(f"    - {r}")

        context_lines.append("")

    final_context_str = "\n".join(context_lines)

    # Logging
    try:
        with open("log/query/final_context_local.json", "w", encoding="utf-8") as f:
            json.dump({"llm_context": context_lines}, f, ensure_ascii=False, indent=2)
    except:
        pass

    # LLM
    chain = PromptTemplate.from_template(LOCAL_SEARCH_SYSTEM_PROMPT) | connection.llm | StrOutputParser()
    t2 = time.time()
    print(f"Thời gian: {t2 - t1:.2f}s")

    return chain.invoke({
        "question": question,
        "context_data": final_context_str
    })



def router_search(question):
    try:
        router_chain = PromptTemplate.from_template(ROUTER_SYSTEM_PROMPT) | connection.llm | JsonOutputParser()
        decision = router_chain.invoke({"question": question})
        destination = decision.get("destination", "LOCAL").upper()

        print(f"   -> Decision: {destination} STRATEGY")


        if destination == "GLOBAL":
            return global_search(question)
        else:
            return local_search(question)

    except Exception as e:
        print(f"Router Error: {e}. Fallback to Local Search.")
        return local_search(question)
