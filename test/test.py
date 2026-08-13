# 通过代码请求
import requests

url = "http://127.0.0.1:8000/api/query"
payload = {"query": "统计2025年各地区销售总额"}   # requests 自动转成 {"query": "..."}

# stream=True 是关键：SSE 是流式响应，不能一次性读完
with requests.post(url, json=payload, stream=True, timeout=(5, 60)) as resp:
    print("状态码:", resp.status_code)
    # 逐行读取流式数据（SSE 每块以 data: 开头、空行分隔）
    for line in resp.iter_lines(decode_unicode=True):
        if line:          # 过滤空行
            print(line)