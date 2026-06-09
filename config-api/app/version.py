import os

def get_git_hash() -> str:
    """Read short commit hash from local .git folder in pure Python (works in local dev)."""
    try:
        # Check container path /app/.git/HEAD
        git_dir = "/app/.git"
        if not os.path.exists(git_dir):
            # Fallback to relative path for host dev
            git_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.git")
            
        head_path = os.path.join(git_dir, "HEAD")
        if not os.path.exists(head_path):
            return ""
            
        with open(head_path, "r") as f:
            head_content = f.read().strip()
            
        if head_content.startswith("ref:"):
            ref_path = head_content.split(" ")[1]  # e.g. refs/heads/main
            # 1. Try to read from loose reference file
            full_ref_path = os.path.join(git_dir, ref_path)
            if os.path.exists(full_ref_path):
                with open(full_ref_path, "r") as f:
                    return f.read().strip()[:7]
            
            # 2. Try to read from packed-refs
            packed_refs_path = os.path.join(git_dir, "packed-refs")
            if os.path.exists(packed_refs_path):
                with open(packed_refs_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or not line:
                            continue
                        parts = line.split(" ")
                        if len(parts) == 2 and parts[1] == ref_path:
                            return parts[0][:7]
        else:
            return head_content[:7]
    except Exception:
        pass
    return ""

def get_display_version() -> str:
    """Get the version string to display. Tag/version is baked into the image itself, local builds fall back to git hash."""
    # 1. Read baked version file if present in the image filesystem
    version_file = "/app/app_version.txt"
    if os.path.exists(version_file):
        try:
            with open(version_file, "r") as f:
                version = f.read().strip()
            if version:
                # Truncate if it's a full 40-character SHA
                if len(version) == 40 and all(c in "0123456789abcdef" for c in version.lower()):
                    return version[:7]
                return version
        except Exception:
            pass

    # 2. Local build: try to extract local git hash from mounted .git
    local_hash = get_git_hash()
    if local_hash:
        return local_hash

    return "local"
