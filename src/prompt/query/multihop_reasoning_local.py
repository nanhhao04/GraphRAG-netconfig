MULTI_HOP_REASONING_PROMPT = """
    Bạn là một chuyên gia mạng AI. Dưới đây là các mối quan hệ trong hệ thống mạng (dạng đồ thị):

    --- Dữ liệu đồ thị (Triples) ---
    {context_data}
    --------------------------------

    Câu hỏi: {question}

    Yêu cầu suy luận (Multi-hop Reasoning):
    1. Xác định các thiết bị được nhắc đến trong câu hỏi.
    2. Dựa vào các mối nối (->), hãy lần theo đường đi để tìm câu trả lời.
    3. Nếu A nối với B, và B nối với C, hãy suy luận mối quan hệ giữa A và C.

    Trả lời ngắn gọn, súc tích bằng tiếng Việt:
    """