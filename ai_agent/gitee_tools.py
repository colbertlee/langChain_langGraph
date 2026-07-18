import os, base64, requests
from dotenv import load_dotenv
load_dotenv()

GITEE_TOKEN = os.getenv("GITEE_TOKEN", "")
GITEE_API = "https://gitee.com/api/v5"

def get_params():
    return {"access_token": GITEE_TOKEN} if GITEE_TOKEN else {}

def handle_gitee_list_repos(args):
    r = requests.get(f"{GITEE_API}/user/repos", params={**get_params(), "per_page": 10}, timeout=15)
    return "\n".join([f"{repo['full_name']}" for repo in r.json()]) if isinstance(r.json(), list) else "Error"

def handle_gitee_get_repo(args):
    r = requests.get(f"{GITEE_API}/repos/{args['owner']}/{args['repo']}", params=get_params(), timeout=15)
    d = r.json()
    return f"{d['full_name']}\nStars: {d.get('stargazers_count',0)}" if "message" not in d else "Error"

def handle_gitee_create_file(args):
    url = f"{GITEE_API}/repos/{args['owner']}/{args['repo']}/contents/{args['path']}"
    data = {**get_params(), "message": args.get("message", "Update"), "content": base64.b64encode(args['content'].encode()).decode()}
    return "Success" if "path" in requests.post(url, json=data, timeout=15).json() else "Error"