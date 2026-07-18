"""调试 Gitee API"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

GITEE_TOKEN = os.getenv("GITEE_TOKEN", "")
print(f"Token from env: {GITEE_TOKEN[:10]}...")

url = "https://gitee.com/api/v5/user/repos"
params = {"access_token": GITEE_TOKEN, "per_page": 3}

response = requests.get(url, params=params, timeout=15)
print(f"Status: {response.status_code}")
data = response.json()
print(f"Type: {type(data)}")

if isinstance(data, list):
    print(f"Repo count: {len(data)}")
    if data:
        print(f"First repo: {data[0].get('full_name')}")
else:
    print(f"Data: {data}")
