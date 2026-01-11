import json
import random
import time
import tiktoken
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_community.vectorstores import Neo4jVector
import src.connection as connection

# Import Prompts
from src.prompt.query.global_search_map_system_prompt import MAP_SYSTEM_PROMPT
from src.prompt.query.global_search_reduce_system_prompt import REDUCE_SYSTEM_PROMPT
from src.prompt.query.local_search_system_prompt import LOCAL_SEARCH_SYSTEM_PROMPT
from src.prompt.query.multihop_reasoning_local import MULTI_HOP_REASONING_PROMPT
from src.prompt.query.router_search import ROUTER_SYSTEM_PROMPT


def count_tokens(text):
    try:
        encoding = tiktoken.get_encoding("cl100k_base") # Encoding chuẩn của GPT-4 (tương đối đúng với Gemini)
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
    all_points = []  # point đểm đánh giá

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

            if res.get('points'):
                for p in res['points']:
                    # Nội dung + Điểm số
                    all_points.append({
                        "description": p.get('description', ''),
                        "score": p.get('score', 0)
                    })
            with open("log/globalsearch.json", "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
                json.dump(all_points, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Lỗi xử lý Chunk {i}: {e}")
            continue

    if not all_points:
        return "Không tìm thấy thông tin phù hợp trong hệ thống."


    all_points.sort(key=lambda x: x['score'], reverse=True)
    top_points = all_points[:50]
    with open("log/top_points.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(top_points, ensure_ascii=False, indent=2))

    formatted_report = "\n".join([f"- [Score: {p['score']}] {p['description']}" for p in top_points])
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
    SEARCH_K = 5
    GRAPH_LIMIT = 100

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

    print(f"   -> Tìm thấy {len(docs_with_score)} Anchor Nodes tiềm năng.")

    candidates = [] # {'text': string, 'score': float}

    for doc, score in docs_with_score:
        # Parse ID
        content_lines = doc.page_content.split("\n")
        dev_id = "UNKNOWN"
        for line in content_lines:
            if line.startswith("id:"):
                dev_id = line.replace("id:", "").strip()
                break

        if dev_id == "UNKNOWN": continue

        traversal_query = f"""
            MATCH path = (start:Entity {{id: $id}})-[*1..3]-(end:Entity)
            UNWIND relationships(path) as r
            RETURN 
                startNode(r).id as src, 
                type(r) as rel, 
                endNode(r).id as tgt,
                length(path) as hops
            LIMIT {GRAPH_LIMIT}
        """

        paths = connection.graph.query(traversal_query, {"id": dev_id})

        for p in paths:
            triple_text = f"({p['src']}) -[{p['rel']}]-> ({p['tgt']})"

            # Công thức: Điểm Vector của Node gốc * Hệ số suy giảm theo khoảng cách (Hops)
            # Hop 1 (trực tiếp): giữ nguyên điểm. Hop 2 (gián tiếp): giảm 50%.
            decay = 1.0 if p['hops'] == 1 else 0.5
            final_score = score * decay

            candidates.append({
                "text": triple_text,
                "score": final_score
            })

    #Loại bỏ trùng lặp (nếu cùng 1 triple xuất hiện nhiều lần, giữ cái có score cao nhất)
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
