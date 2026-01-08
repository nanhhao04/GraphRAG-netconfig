from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_community.vectorstores import Neo4jVector
import src.connection as connection

# Import Prompts
from src.prompt.query.global_search_map_system_prompt import MAP_SYSTEM_PROMPT
from src.prompt.query.global_search_reduce_system_prompt import REDUCE_SYSTEM_PROMPT
from src.prompt.query.local_search_system_prompt import LOCAL_SEARCH_SYSTEM_PROMPT
from src.prompt.query.multihop_reasoning_local import MULTI_HOP_REASONING_PROMPT


def global_search(question):
    print("GLOBAL SEARCH MODE (Scanning Communities...)")

    # 1. Lấy danh sách báo cáo từ các Community
    # Lưu ý: Nếu bước Summarization chưa chạy xong, lệnh này sẽ trả về rỗng
    try:
        communities = connection.graph.query("""
            MATCH (c:Community) 
            RETURN c.id as id, c.title as title, c.summary as summary, c.rating as rating
        """)
    except Exception as e:
        return f"Lỗi truy vấn Neo4j: {e}"

    if not communities:
        return "⚠️ Hệ thống chưa có dữ liệu tổng quan (Community Nodes). Hãy chạy bước 1 (Ingestion -> Summarize) trước."

    print(f"   -> Tìm thấy {len(communities)} báo cáo cộng đồng. Đang phân tích...")

    # 2. MAP STEP: Quét qua từng báo cáo để tìm điểm liên quan
    map_chain = PromptTemplate.from_template(MAP_SYSTEM_PROMPT) | connection.llm | JsonOutputParser()
    extracted_info = []

    for c in communities:
        # Tạo ngữ cảnh cho AI đọc
        context = f"""
        Community ID: {c['id']}
        Title: {c['title']}
        Rating: {c['rating']}
        Summary: {c['summary']}
        """
        try:
            # AI lọc thông tin liên quan đến câu hỏi
            res = map_chain.invoke({"question": question, "context_data": context})

            # Nếu có điểm thông tin hữu ích (points), lưu lại
            if res.get('points'):
                for p in res['points']:
                    extracted_info.append(f"- [Từ cụm {c['title']}]: {p['description']} (Score: {p.get('score', 0)})")
        except Exception as e:
            # Bỏ qua các lỗi nhỏ khi parse JSON của từng cụm
            continue

    if not extracted_info:
        return "Rất tiếc, tôi không tìm thấy thông tin tổng quan nào liên quan đến câu hỏi này trong các báo cáo cộng đồng."

    # 3. REDUCE STEP: Tổng hợp lại thành câu trả lời cuối cùng
    print(f"   -> Tổng hợp {len(extracted_info)} điểm thông tin quan trọng...")
    reduce_chain = PromptTemplate.from_template(REDUCE_SYSTEM_PROMPT) | connection.llm | StrOutputParser()

    final_answer = reduce_chain.invoke({
        "question": question,
        "report_data": "\n".join(extracted_info)
    })

    return final_answer


def local_search(question):
    print("LOCAL SEARCH MODE (Multi-hop Reasoning...)")

    # 1. Vector Search: Tìm "Điểm khởi đầu" (Anchor Nodes)
    try:
        vector_store = Neo4jVector.from_existing_index(
            embedding=connection.embeddings,
            url=connection.cfg["NEO4J_URI"],
            username=connection.cfg["NEO4J_USERNAME"],
            password=connection.cfg["NEO4J_PASSWORD"],
            index_name="entity_index"
        )
        # Tìm 2 thực thể giống nhất làm điểm neo
        docs = vector_store.similarity_search(question, k=2)
    except Exception as e:
        return f"Lỗi Vector Index: {e}"

    if not docs:
        return "Không tìm thấy thiết bị hoặc thực thể nào khớp với câu hỏi."

    print(f"   -> Điểm khởi đầu suy luận: {len(docs)} node.")
    context_triples = set()  # Dùng set để loại bỏ trùng lặp

    # 2. Graph Traversal (Multi-hop Expansion)
    # Thay vì chỉ tìm 1-hop, ta tìm chuỗi quan hệ sâu 2 bước
    for d in docs:
        # Lấy ID an toàn
        content_lines = d.page_content.split("\n")
        dev_id = "UNKNOWN"
        for line in content_lines:
            if line.startswith("id:"):
                dev_id = line.replace("id:", "").strip()
                break

        if dev_id == "UNKNOWN": continue

        # --- QUERY QUAN TRỌNG CHO MULTI-HOP ---
        # [*1..2] nghĩa là tìm cả hàng xóm (1 bước) và hàng xóm của hàng xóm (2 bước)
        traversal_query = """
            MATCH path = (start:Entity {id: $id})-[*1..2]-(end:Entity)
            UNWIND relationships(path) as r
            RETURN 
                startNode(r).id as src, 
                type(r) as rel, 
                endNode(r).id as tgt,
                startNode(r).type as src_type,
                endNode(r).type as tgt_type
            LIMIT 50
        """

        paths = connection.graph.query(traversal_query, {"id": dev_id})

        for p in paths:
            triple = f"({p['src']} : {p['src_type']}) -[{p['rel']}]-> ({p['tgt']} : {p['tgt_type']})"
            context_triples.add(triple)

    # 3. Tạo Context cho LLM
    if not context_triples:
        return "Tìm thấy thiết bị nhưng không có thông tin kết nối xung quanh."

    # Ghép các triple lại thành văn bản
    context_text = "\n".join(context_triples)

    print(f"   -> Thu thập được {len(context_triples)} mối quan hệ (Triples) để suy luận.")

    # 4. Answer Generation

    PromptTemplate.from_template(MAP_SYSTEM_PROMPT)
    chain = PromptTemplate.from_template(LOCAL_SEARCH_SYSTEM_PROMPT) | connection.llm | StrOutputParser()

    return chain.invoke({
        "question": question,
        "context_data": context_text
    })