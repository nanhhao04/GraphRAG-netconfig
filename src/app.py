import streamlit as st
import time
import os
import sys

# Đảm bảo python tìm thấy các module trong thư mục src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import các module của bạn
import src.connection as connection
from src.graph import (run_ingestion, run_clustering_louvain, run_summarization)
from src.retrieval import router_search, global_search, \
    local_search  # Lưu ý: route_question hay router_search tuỳ tên hàm bạn đặt

st.set_page_config(
    page_title="Network GraphRAG AI",
    page_icon="🕸️",
    layout="wide"
)

# CSS TÙY CHỈNH
st.markdown("""
<style>
    /* Chỉnh màu nền và border cho khung chat */
    .stChatMessage {
        border-radius: 15px;
        padding: 10px;
        margin-bottom: 10px;
        border: 1px solid #e0e0e0;
    }
    /* Làm đậm các thẻ Header trong Markdown */
    h2, h3 {
        color: #2E86C1; /* Màu xanh chuyên nghiệp */
    }
    /* Hiệu ứng cho status box */
    .stStatusWidget {
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)


#HÀM XỬ LÝ FILE UPLOAD
def process_uploaded_yaml(uploaded_file):
    """
    Hàm đọc file upload từ Streamlit với cơ chế bắt lỗi an toàn.
    """
    if uploaded_file is None:
        st.warning("Vui lòng upload file YAML trước khi xây dựng Graph.")
        return None

    try:
        content = uploaded_file.read().decode("utf-8")
        if not content.strip():
            st.error("Lỗi: File tải lên bị rỗng!")
            return None
        return content
    except Exception as e:
        st.error(f"Lỗi khi đọc file: {e}")
        return None


# --- INIT CONNECTION (Chỉ chạy 1 lần) ---
@st.cache_resource
def setup_connections():
    try:
        connection.init_connections()
        return True
    except Exception as e:
        st.error(f"Lỗi kết nối Neo4j/Gemini: {e}")
        return False


if not setup_connections():
    st.stop()

# ==========================================
# --- SIDEBAR (QUAN TRỌNG: KHÔNG ĐƯỢC THIẾU) ---
# ==========================================
with st.sidebar:
    st.title(" Admin Control")
    st.markdown("---")

    st.subheader("1. Quản lý Dữ liệu Graph")
    uploaded_file = st.file_uploader("Upload file YAML cấu hình mạng", type=["yml", "yaml"])

    if st.button("Xây dựng Graph (Full Flow)", type="primary"):
        # Gọi hàm xử lý file an toàn
        yaml_content = process_uploaded_yaml(uploaded_file)

        # Chỉ chạy tiếp nếu có nội dung
        if yaml_content:
            with st.status("Đang xây dựng Knowledge Graph...", expanded=True) as status:
                st.write("1. Reading & Ingesting Data...")
                run_ingestion(yaml_content)

                st.write("2. Running Louvain Clustering...")
                run_clustering_louvain()

                status.update(label="Xây dựng Graph hoàn tất!", state="complete", expanded=False)
            st.success("Hệ thống đã sẵn sàng!")

    st.markdown("---")
    st.subheader("2. Chế độ Tìm kiếm")
    # ĐÂY LÀ CHỖ KHAI BÁO BIẾN search_mode
    search_mode = st.radio(
        "Chọn chế độ:",
        ("Auto (AI Router)", "Global Search (Tổng quan)", "Local Search (Chi tiết)")
    )

    st.markdown("---")
    if st.button("Xóa lịch sử chat"):
        st.session_state.messages = []
        st.rerun()


# MAIN CHAT INTERFACE
st.title("🕸️ Network GraphRAG Assistant")
st.caption("Powered by Neo4j & Gemini 1.5 Flash | Graph-based Reasoning")

# 1. Khởi tạo lịch sử chat
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant",
         "content": "Xin chào! Tôi là trợ lý mạng AI. Tôi đã sẵn sàng phân tích hệ thống của bạn."}
    ]

# 2. Hiển thị lịch sử chat
for msg in st.session_state.messages:
    avatar = "🤖" if msg["role"] == "assistant" else "🧑‍💻"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# 3. Xử lý Input
if prompt := st.chat_input("VD: Hệ thống có điểm đơn thất bại (SPOF) nào không?"):
    # Hiển thị câu hỏi User
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Xử lý câu trả lời AI
    with st.chat_message("assistant", avatar="🤖"):
        message_placeholder = st.empty()
        full_response = ""

        # Dùng st.status thay cho spinner
        with st.status("Đang phân tích hệ thống...", expanded=True) as status:
            try:
                # Logic chọn hàm search (Sử dụng biến search_mode từ sidebar)
                if search_mode == "Auto (AI Router)":
                    st.write("Targeting: AI Router Decision...")
                    # Lưu ý: Import đúng tên hàm router của bạn (route_question hoặc router_search)
                    response_text = router_search(prompt)
                elif search_mode == "Global Search (Tổng quan)":
                    st.write("Targeting: Global Map-Reduce Analysis...")
                    response_text = global_search(prompt)
                else:
                    st.write("Targeting: Local Entity Traversal...")
                    response_text = local_search(prompt)

                status.update(label="Phân tích hoàn tất!", state="complete", expanded=False)

                # Hiệu ứng gõ chữ
                for chunk in response_text.split(" "):
                    full_response += chunk + " "
                    time.sleep(0.01)
                    message_placeholder.markdown(full_response + "▌")

                message_placeholder.markdown(full_response)

            except Exception as e:
                status.update(label="Err: Có lỗi xảy ra!", state="error")
                st.error(f"Chi tiết lỗi: {e}")
                full_response = "Xin lỗi, tôi gặp sự cố khi truy xuất dữ liệu."
                message_placeholder.markdown(full_response)

    st.session_state.messages.append({"role": "assistant", "content": full_response})