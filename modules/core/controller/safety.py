ALLOWED_REPOS = ["/Users/lionelchong/sandbox"]

def check_repo_path(path: str):
    if not any(path.startswith(p) for p in ALLOWED_REPOS):
        raise PermissionError(f"Repo not allowed: {path}")
