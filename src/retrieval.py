from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_community.vectorstores import Neo4jVector

from src.connection import graph, llm, embeddings, cfg
# Import Prompts
from src.prompt.query.global_search_map_system_prompt import MAP_SYSTEM_PROMPT
from src.prompt.query.global_search_reduce_system_prompt import REDUCE_SYSTEM_PROMPT
from src.prompt.query.local_search_system_prompt import LOCAL_SEARCH_SYSTEM_PROMPT


def global_search(question):
    print("GLOBAL SEARCH MODE")

    # 1. MAP: Scan Community Reports
    communities = graph.query("MATCH (c:Community) RETURN c.title, c.summary")

    map_chain = PromptTemplate.from_template(MAP_SYSTEM_PROMPT) | llm | JsonOutputParser()
    extracted_info = []

    for c in communities:
        context = f"Title: {c['c.title']}\nSummary: {c['c.summary']}"
        try:
            res = map_chain.invoke({"question": question, "context_data": context})
            if res.get('points'):
                for p in res['points']:
                    extracted_info.append(f"- {p['description']}")
        except:
            pass

    if not extracted_info:
        return "Không có thông tin tổng quan."

    # 2. REDUCE: Synthesize
    reduce_chain = PromptTemplate.from_template(REDUCE_SYSTEM_PROMPT) | llm | StrOutputParser()
    return reduce_chain.invoke({
        "question": question,
        "report_data": "\n".join(extracted_info)
    })


def local_search(question):
    print("LOCAL SEARCH MODE")

    # 1. Vector Search tìm Device
    try:
        vector_store = Neo4jVector.from_existing_index(
            embeddings,
            url=cfg["NEO4J_URI"], username=cfg["NEO4J_USERNAME"], password=cfg["NEO4J_PASSWORD"],
            index_name="entity_index"
        )
        docs = vector_store.similarity_search(question, k=2)
    except:
        return "Lỗi Vector Index."

    if not docs: return "Không tìm thấy thiết bị."

    # 2. Lấy Neighbors (1-hop)
    context = []
    for d in docs:
        dev_id = d.page_content.split("\n")[0].replace("id: ", "")  # Simple parse
        neighbors = graph.query(
            "MATCH (d:Device {id: $id})-[r]-(n) RETURN type(r), n.id",
            {"id": dev_id}
        )
        context.append(f"Device: {dev_id}\nNeighbors: {neighbors}")

    # 3. Answer
    chain = PromptTemplate.from_template(LOCAL_SEARCH_SYSTEM_PROMPT) | llm | StrOutputParser()
    return chain.invoke({
        "question": question,
        "context_data": "\n".join(context)
    })