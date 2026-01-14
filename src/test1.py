

import yaml
import json
import re
import os


INPUT_FILENAME = "../data/networkconfig.yml"

# Định nghĩa các loại Relationship ngắn gọn (Enum)
REL_TYPES = {
    "CONFIG": "HAS_CONFIG",
    "INTERFACE": "HAS_INTERFACE",
    "BOND": "HAS_BOND",
    "VLAN": "HAS_VLAN",
    "IP": "HAS_IP",
    "ROUTE": "HAS_ROUTE",
    "ITEM": "CONTAINS_ITEM"
}


# ==========================================
# 2. HÀM TẠO DESCRIPTION "THÔ" (RECURSIVE SUMMARY)
# ==========================================
def generate_deep_summary(data):
    """
    Hàm này biến đổi toàn bộ Dict/List lồng nhau thành một chuỗi string
    ngắn gọn, dễ đọc cho LLM. Nó sẽ đào sâu xuống tận đáy.
    """
    if isinstance(data, dict):
        # Lọc bỏ các trường ít giá trị cho LLM để tiết kiệm token
        filtered_data = {k: v for k, v in data.items() if k not in ['renderer', 'version', 'dhcp4', 'metric']}

        parts = []
        for k, v in filtered_data.items():
            val_str = generate_deep_summary(v)
            # Nếu giá trị rỗng hoặc quá ngắn thì format kiểu key: val
            # Nếu giá trị dài (là object con) thì format kiểu key { ... }
            if isinstance(v, (dict, list)) and len(v) > 0:
                parts.append(f"{k} {{ {val_str} }}")
            else:
                parts.append(f"{k}: {val_str}")
        return ", ".join(parts)

    elif isinstance(data, list):
        items = [generate_deep_summary(item) for item in data]
        return f"[{', '.join(items)}]"

    else:
        return str(data)


# ==========================================
# 3. CORE LOGIC
# ==========================================
nodes_list = []
edges_list = []
existing_node_names = set()


def add_node(name, type_node, raw_config_data, extra_desc=""):
    """
    Tạo Node với Description chứa toàn bộ thông tin cấu hình bên dưới nó.
    """
    name_upper = str(name).upper().replace(" ", "_")

    # Tạo Description "Thần thánh": Kết hợp mô tả phụ + Summary toàn bộ config con
    config_summary = generate_deep_summary(raw_config_data)

    if extra_desc:
        full_desc = f"{extra_desc}. Config Details: {config_summary}"
    else:
        full_desc = f"Config Details: {config_summary}"

    # Tránh trùng lặp
    if name_upper not in existing_node_names:
        nodes_list.append({
            "name": name_upper,
            "type": type_node,
            "desc": full_desc
        })
        existing_node_names.add(name_upper)

    return name_upper


def add_edge(source, target, desc, strength="10"):
    edges_list.append({
        "source": str(source).upper().replace(" ", "_"),
        "target": str(target).upper().replace(" ", "_"),
        "desc": desc,
        "strength": strength
    })


def process_recursive_structure(key, value, parent_name):
    """
    Hàm duyệt cây để tạo ra các Node con và nối dây về cha.
    """
    current_name = key

    # --- CASE 1: DICTIONARY (Interface, Vlan, Bond...) ---
    if isinstance(value, dict):
        # Xác định loại Node
        node_type = "SECTION"
        if any(x in key for x in ["eth", "eno", "wan", "lan"]):
            node_type = "INTERFACE"
        elif "bond" in key:
            node_type = "BOND"
        elif "vlan" in key:
            node_type = "VLAN"
        elif key == "network":
            node_type = "CONFIG_ROOT"

        # Tạo Node cho chính phần tử này
        # LƯU Ý: value chính là dict chứa toàn bộ thông tin con, ta truyền vào add_node
        real_name = add_node(current_name, node_type, value, extra_desc=f"Configuration block for {key}")

        # Nối với cha
        if parent_name:
            rel_type = "HAS_" + node_type
            if node_type == "SECTION": rel_type = "CONTAINS"
            add_edge(parent_name, real_name, rel_type)

        # Đệ quy xuống con
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                process_recursive_structure(k, v, real_name)

    # --- CASE 2: LIST (Addresses, Routes...) ---
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            if isinstance(item, str) and key == 'addresses':
                # Node IP
                ip_desc = f"IP Address: {item}"
                add_node(item, "IP_ADDRESS", {}, extra_desc=ip_desc)  # IP ko có config con nên dict rỗng
                add_edge(parent_name, item, "HAS_IP")

            elif isinstance(item, dict):
                # Route item hoặc list item phức tạp
                item_name = f"{parent_name}_ITEM_{idx}"
                if 'to' in item:  # Nếu là Route
                    item_name = f"ROUTE_TO_{item['to']}"
                    add_node(item_name, "ROUTE", item, extra_desc=f"Routing entry")
                    add_edge(parent_name, item_name, "HAS_ROUTE")
                else:
                    process_recursive_structure(f"ITEM_{idx}", item, parent_name)


# ==========================================
# 4. MAIN EXECUTION
# ==========================================
if os.path.exists(INPUT_FILENAME):
    with open(INPUT_FILENAME, 'r', encoding='utf-8') as f:
        file_content = f.read()

    # Tách document chuẩn hơn, loại bỏ các phần rỗng
    raw_docs = [doc for doc in file_content.strip().split('---') if doc.strip()]

    for raw_doc in raw_docs:
        # 1. Regex mạnh hơn để bắt tên thiết bị (xử lý cả xuống dòng, khoảng trắng)
        # Tìm dòng bắt đầu bằng # NODE ... : <TÊN>
        # Match group 1: Tên thiết bị, Match group 2: Mô tả trong ngoặc (nếu có)
        match = re.search(r"#\s*NODE\s*\d+\s*:\s*([^(\n]+)(?:\(([^)]+)\))?", raw_doc)

        if match:
            device_name = match.group(1).strip()
            device_note = match.group(2).strip() if match.group(2) else "Network Device"
        else:
            # Fallback nếu không khớp regex (tránh UNKNOWN nếu có thể)
            if "network:" in raw_doc:
                device_name = f"UNKNOWN_DEVICE_{len(nodes_list)}"
                device_note = "Parsed from raw config"
            else:
                continue  # Bỏ qua các đoạn text rác không phải config

        try:
            data = yaml.safe_load(raw_doc)
            if data and 'network' in data:
                # 2. TẠO NODE DEVICE (GỐC)
                # Đây là chỗ quan trọng: device_name sẽ chứa TOÀN BỘ 'data['network']' trong desc
                root_name = add_node(device_name, "DEVICE", data['network'], extra_desc=device_note)

                # 3. Duyệt con để tạo graph chi tiết
                process_recursive_structure('network', data['network'], root_name)

        except Exception as e:
            print(f"Error parsing block {device_name}: {e}")

# ==========================================
# 5. OUTPUT
# ==========================================
output_data = {
    "entities": nodes_list,
    "relationships": edges_list
}

# Print sample để kiểm tra
print(json.dumps(output_data['entities'][:5], indent=2, ensure_ascii=False))
print("...")

# (Optional) Lưu ra file
with open('log/graph_output_test.json', 'w', encoding='utf-8') as f:
    json.dump(output_data, f, indent=2, ensure_ascii=False)