import os, base64, requests
from dotenv import load_dotenv
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")

def get_headers():
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN: h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h

def handle_github_list_repos(args):
    r = requests.get("https://api.github.com/user/repos", headers=get_headers(), params={"per_page": 10}, timeout=10)
    return "\n".join([f"{repo['full_name']}" for repo in r.json()]) if r.status_code == 200 else "Error"

def handle_github_get_repo(args):
    owner, repo = args.get("owner", ""), args.get("repo", "")
    r = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=get_headers(), timeout=10)
    d = r.json()
    return f"{d['full_name']}\nStars: {d.get('stargazers_count',0)}\n{d.get('description','')}" if "message" not in d else "Error"

def handle_github_create_file(args):
    url = f"https://api.github.com/repos/{args['owner']}/{args['repo']}/contents/{args['path']}"
    data = {"message": args.get("message", "Update"), "content": base64.b64encode(args['content'].encode()).decode()}
    r = requests.put(url, headers=get_headers(), json=data, timeout=10)
    return "Success" if r.status_code in [200, 201] else "Error"