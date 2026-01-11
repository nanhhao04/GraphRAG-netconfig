# SỬA LẠI PROMPT: Thêm dấu ngoặc kép {{ }} vào phần Example Output
BATCH_COMMUNITY_REPORT_PROMPT = """
You are an expert Network Analyst. I will provide data for multiple communities (clusters) of network entities.
The data for each community is separated by a header like "--- COMMUNITY ID: <id> ---".

For EACH community, generate a report in JSON format with the following keys:
- "id": The community ID provided in the header.
- "title": A short, descriptive title for the cluster.
- "summary": A comprehensive summary of the devices and their roles.
- "rating": A risk/importance score (0-100).
- "rating_explanation": Why you gave this score.
- "findings": A list of specific insights (strings).

Output must be a RAW JSON LIST of objects. Do not wrap in markdown blocks.

Example Output:
[
  {{"id": "1", "title": "Core Spine", "summary": "...", "rating": 90, "findings": ["..."]}},
  {{"id": "2", "title": "Leaf Access", "summary": "...", "rating": 50, "findings": ["..."]}}
]

Input Data:
{input_text}
"""