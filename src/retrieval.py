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
    print("LOCAL SEARCH MODE (Token-based Pruning Strategy)...")
    t1 = time.time()

    MAX_CONTEXT_TOKENS = 4000
    SEARCH_K = 3
    GRAPH_LIMIT = 50

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
        with open("log/query/docs_with_score_local.txt", "w", encoding="utf-8") as f:
            for doc, score in docs_with_score:
                f.write(f"SCORE: {score}\n")
                f.write(doc.page_content + "\n")
                f.write(str(doc.metadata) + "\n")
                f.write("-" * 50 + "\n")

    except Exception as e:
        return f"Lỗi Vector Index: {e}"

    if not docs_with_score:
        return "Không tìm thấy thiết bị nào liên quan."

    print(f"   -> Tìm thấy {len(docs_with_score)} Anchor Nodes tiềm năng.")

    candidates = [] # {'text': string, 'score': float}

    for doc, score in docs_with_score:
        # Parse ID
        #content_lines = doc.page_content.split("\n")
        dev_id = doc.page_content.strip()
        if dev_id == "UNKNOWN": continue

        traversal_query = """
            MATCH (src:Entity {id: $id})-[r]-(tgt:Entity)
            WHERE type(r) <> 'IN_COMMUNITY'
            RETURN 
                src.type as src_type, src.id as src_id, src.desc as src_desc,
                type(r) as rel_type, r.desc as rel_desc,
                tgt.type as tgt_type, tgt.id as tgt_id, tgt.desc as tgt_desc
            LIMIT $limit
        """

        paths = connection.graph.query(traversal_query, {"id": dev_id, "limit": GRAPH_LIMIT})

        for p in paths:
            '''
            triple_text = f"({p['src']}) -[{p['rel']}]-> ({p['tgt']})"
            # Hop 1 giữ nguyên điểm. Hop 2 (gián tiếp): giảm 50%.
            decay = 1.0 if p['hops'] == 1 else 0.5
            final_score = score * decay
            '''

            src_info = f"[{p['src_type']}] {p['src_id']}"
            if p.get('src_desc'):
                src_info += f" ({p['src_desc']})"
            tgt_info = f"[{p['tgt_type']}] {p['tgt_id']}"
            if p.get('tgt_desc'):
                tgt_info += f" ({p['tgt_desc']})"
            rel_info = f"--[{p['rel_type']}"
            if p.get('rel_desc'):
                rel_info += f": {p['rel_desc']}"
            rel_info += "]-->"
            triple_text = f"{src_info} {rel_info} {tgt_info}"
            final_score = score

            candidates.append({
                "text": triple_text,
                "score": final_score
            })

            candidates.append({
                "text": triple_text,
                "score": final_score
            })

    #Loại bỏ trùng lặp
    unique_candidates = {}
    for c in candidates:
        txt = c['text']
        if txt not in unique_candidates or c['score'] > unique_candidates[txt]['score']:
            unique_candidates[txt] = c

    sorted_candidates = list(unique_candidates.values())

    # Sắp xếp giảm dần theo điểm Score
    sorted_candidates.sort(key=lambda x: x['score'], reverse=True)

    print(f"   -> Tổng hợp được {len(sorted_candidates)} triples ứng viên. Bắt đầu cắt gọt theo Token...")

    # Thêm Context Window cho đến khi đầy
    final_context = []
    current_tokens = 0

    for item in sorted_candidates:
        item_tokens = count_tokens(item['text'])
        if current_tokens + item_tokens > MAX_CONTEXT_TOKENS:
            continue

        final_context.append(item['text'])
        current_tokens += item_tokens

    log_data = {
        "summary_stats": {
            "total_candidates": len(sorted_candidates),
            "final_context_count": len(final_context),
            "total_tokens_used": current_tokens
        },
        "final_context_used_for_llm": final_context,
        "all_candidates_sorted": sorted_candidates
    }

    with open("log/query/final_context_local.json", "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    print(f"   -> Context cuối cùng: {len(final_context)} triples ({current_tokens} tokens).")

    if not final_context:
        return "Không tìm thấy thông tin kết nối phù hợp."


    context_text = "\n".join(final_context)

    chain = PromptTemplate.from_template(LOCAL_SEARCH_SYSTEM_PROMPT) | connection.llm | StrOutputParser()
    t2 = time.time()
    print(f"Thời gian local search: {t2 - t1} (s)")

    return chain.invoke({
        "question": question,
        "context_data": context_text
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
        with open("log/query/docs_with_score_local.txt", "w", encoding="utf-8") as f:
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



def local_search_test2(question):
    print("LOCAL SEARCH MODE (Graph → Device Summary Context)...")
    t1 = time.time()

    MAX_CONTEXT_TOKENS = 4000
    SEARCH_K = 5  # Có thể tăng lên vì kết quả giờ chất lượng hơn
    GRAPH_LIMIT = 50

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
    except Exception as e:
        return f"Lỗi Vector Index: {e}"

    if not docs_with_score:
        return "Không tìm thấy thiết bị nào liên quan."

    print(f"   -> Tìm thấy {len(docs_with_score)} Anchor Nodes.")

    device_data = defaultdict(lambda: {
        "type": "DEVICE",
        "desc": "",
        "interfaces": defaultdict(dict),
        "routes": []
    })
    interface_to_device_map = {}

    # DANH SÁCH CÁC TYPE ĐƯỢC COI LÀ GIAO DIỆN MẠNG
    INTERFACE_TYPES = ["INTERFACE", "BOND", "VLAN", "BRIDGE", "PORT", "ETHERNET", "SECTION"]

    traversal_query = """
        MATCH (src:Entity {id: $id})-[r]-(tgt:Entity)
        WHERE type(r) <> 'IN_COMMUNITY'
        RETURN 
            src.type as src_type, src.id as src_id, src.desc as src_desc,
            type(r) as rel_type, r.desc as rel_desc,
            tgt.type as tgt_type, tgt.id as tgt_id, tgt.desc as tgt_desc
        LIMIT $limit
    """

    for doc, score in docs_with_score:
        dev_id = doc.page_content.strip()
        if dev_id == "UNKNOWN": continue

        results = connection.graph.query(traversal_query, {"id": dev_id, "limit": GRAPH_LIMIT})

        for row in results:
            s_type, s_id, s_desc = row['src_type'], row['src_id'], row['src_desc']
            t_type, t_id, t_desc = row['tgt_type'], row['tgt_id'], row['tgt_desc']

            # Kiểm tra xem type có thuộc nhóm Interface không (Fix quan trọng)
            s_is_interface = any(x in str(s_type) for x in INTERFACE_TYPES)
            t_is_interface = any(x in str(t_type) for x in INTERFACE_TYPES)

            # CASE A: DEVICE <-> INTERFACE/BOND/VLAN
            if s_type == 'DEVICE' and t_is_interface:
                device_data[s_id]['desc'] = s_desc
                device_data[s_id]['interfaces'][t_id]['desc'] = t_desc
                interface_to_device_map[t_id] = s_id

            elif t_type == 'DEVICE' and s_is_interface:
                device_data[t_id]['desc'] = t_desc
                device_data[t_id]['interfaces'][s_id]['desc'] = s_desc
                interface_to_device_map[s_id] = t_id

            # CASE B: INTERFACE <-> IP/VLAN (Map ngược về Device)
            if s_is_interface and t_type == 'IP_ADDRESS':
                if s_id in interface_to_device_map:
                    root = interface_to_device_map[s_id]
                    device_data[root]['interfaces'][s_id]['ip'] = t_id

            elif t_is_interface and s_type == 'IP_ADDRESS':
                if t_id in interface_to_device_map:
                    root = interface_to_device_map[t_id]
                    device_data[root]['interfaces'][t_id]['ip'] = s_id

            # CASE C: DEVICE <-> ROUTE
            if s_type == 'DEVICE' and t_type == 'ROUTE':
                device_data[s_id]['routes'].append(f"{t_id} ({t_desc})")
            elif t_type == 'DEVICE' and s_type == 'ROUTE':
                device_data[t_id]['routes'].append(f"{s_id} ({s_desc})")

    # --- RENDER CONTEXT ---
    final_context = []
    current_tokens = 0

    for dev_id, info in device_data.items():
        if not info['interfaces'] and not info['routes']: continue

        lines = [f"### DEVICE: {dev_id}"]
        if info['desc']: lines.append(f"   Description: {info['desc']}")

        if info['interfaces']:
            lines.append("   INTERFACES:")
            for iface, data in info['interfaces'].items():
                line = f"   - {iface}"
                if data.get('ip'): line += f" | IP: {data['ip']}"
                # Rút gọn desc để tiết kiệm token
                if data.get('desc'):
                    short = data['desc'].split('. ')[0]
                    line += f" ({short})"
                lines.append(line)

        if info['routes']:
            lines.append("   ROUTING TABLE:")
            for r in info['routes']: lines.append(f"   - {r}")

        block = "\n".join(lines)
        if current_tokens + len(block) / 4 > MAX_CONTEXT_TOKENS: break
        final_context.append(block)
        current_tokens += len(block) / 4

    if not final_context:
        return "Không tìm thấy thông tin cấu hình chi tiết."

    context_text = "\n\n".join(final_context)

    # Debug log
    with open("log/query/final_context_local.json", "w", encoding="utf-8") as f:
        json.dump(final_context, f, ensure_ascii=False, indent=2)

    chain = PromptTemplate.from_template(LOCAL_SEARCH_SYSTEM_PROMPT) | connection.llm | StrOutputParser()

    t2 = time.time()
    print(f"Thời gian local search: {t2 - t1:.2f}s")

    return chain.invoke({
        "question": question,
        "context_data": context_text
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
