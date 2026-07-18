from datetime import datetime
import math, os, json
from langchain_core.tools import tool

_rag = None
def set_rag_instance(r): global _rag; _rag = r
def get_rag_instance(): return _rag

@tool
def get_current_time() -> str: return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def calculate(expression: str):
    try: return eval(expression.replace("^", "**"), {"__builtins__": None}, {"sin": math.sin, "cos": math.cos, "sqrt": math.sqrt, "pi": math.pi, "e": math.e})
    except: return "Error"

@tool
def search_web(query: str) -> str:
    try:
        from serpapi import GoogleSearch
        from config import SERPAPI_API_KEY
        if not SERPAPI_API_KEY: return "Configure SERPAPI_API_KEY"
        results = GoogleSearch({"q": query, "api_key": SERPAPI_API_KEY, "num": 5}).get_dict()
        return "\n\n".join([f"{r["title"]}\n{r["snippet"]}" for r in results.get("organic_results", [])[:5]])
    except: return "Error"

@tool
def query_knowledge_base(query: str) -> str:
    rag = get_rag_instance()
    return rag.query(query) if rag else "Initialize KB"

@tool
def get_weather(city: str) -> str:
    try:
        import requests
        r = requests.get(f"http://wttr.in/{city}?format=j1", timeout=15)
        if r.status_code == 200:
            d = r.json().get("current_condition", [{}])[0]
            return f"{city}: {d.get("temp_C")}C, Humidity: {d.get("humidity")}%"
        return "Error"
    except: return "Error"

@tool
def github_search(query: str) -> str:
    try:
        import requests
        r = requests.get("https://api.github.com/search/repositories", params={"q": query, "per_page": 5}, timeout=15)
        return "\n".join([f"{i["full_name"]} - {i.get("stargazers_count",0)} stars" for i in r.json().get("items", [])])
    except: return "Error"

def get_all_tools(): return [get_current_time, calculate, search_web, query_knowledge_base, get_weather, github_search]