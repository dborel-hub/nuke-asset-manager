"""
Updater - brings an installed Asset Manager up to date from GitHub.

How it decides what to download (no file list to maintain):
  GitHub's API lists every file of the repository with its git "blob" hash.
  The same hash is computed for each installed file; only files whose hash
  differs (or that don't exist yet) are downloaded. Files that were removed
  from the repository are deleted. data/ (your library) and bin/ (ffmpeg)
  are never touched.

Downloads go to a temporary folder first and are moved into place only if
all of them succeeded, so a dropped connection can't leave a half update.

Standard library only: used inside Nuke AND by install.pyw.
"""

import os
import re
import json
import shutil
import hashlib
import tempfile
import urllib.error
import urllib.parse
import urllib.request

REPO_FOLDER = "Asset Manager/"          # plugin folder inside the repository
PROTECTED = ("data", "bin", "__pycache__")
USER_AGENT = "AssetManager-Updater"
TIMEOUT = 20


class UpdateError(Exception):
    pass


# ---------------------------------------------------------------- settings
def read_setting(plugin_root, name, default=None):
    """Read NAME = "value" from config.py without importing the package."""
    try:
        with open(os.path.join(plugin_root, "config.py"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return default
    m = re.search(r'^%s\s*=\s*"([^"]*)"' % re.escape(name), text, re.M)
    return m.group(1) if m else default


def repo_settings(plugin_root, fallback_root=None):
    for root in (plugin_root, fallback_root):
        if root:
            repo = read_setting(root, "GITHUB_REPO")
            if repo:
                return repo, read_setting(root, "GITHUB_BRANCH", "main")
    raise UpdateError("GITHUB_REPO not set in config.py")


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


# ---------------------------------------------------------------- network
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Repository or branch not found on GitHub (is it public?)")
        if e.code == 403:
            raise UpdateError("GitHub refused the request (rate limit?) - try again in a few minutes")
        raise UpdateError(f"GitHub error {e.code}")
    except urllib.error.URLError as e:
        raise UpdateError(f"No connection to GitHub ({e.reason})")


def raw_url(repo, branch, path):
    return "https://raw.githubusercontent.com/%s/%s/%s" % (
        repo, branch, urllib.parse.quote(path))


def remote_version(repo, branch):
    """APP_VERSION of the latest config.py on GitHub (1 small request)."""
    text = _get(raw_url(repo, branch, REPO_FOLDER + "config.py")).decode("utf-8", "replace")
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]*)"', text, re.M)
    return m.group(1) if m else None


def remote_files(repo, branch):
    """{relative path inside the plugin: git blob sha} from the GitHub tree API."""
    data = json.loads(_get("https://api.github.com/repos/%s/git/trees/%s?recursive=1"
                           % (repo, urllib.parse.quote(branch))))
    files = {}
    for entry in data.get("tree", []):
        path = entry.get("path", "")
        if entry.get("type") != "blob" or not path.startswith(REPO_FOLDER):
            continue
        rel = path[len(REPO_FOLDER):]
        if rel.split("/")[0] in PROTECTED or rel.endswith(".pyc"):
            continue
        files[rel] = entry["sha"]
    if not files:
        raise UpdateError(f'No "{REPO_FOLDER.rstrip("/")}" folder found in {repo}')
    return files


# ---------------------------------------------------------------- local
def git_blob_sha(path):
    """Same hash git/GitHub use for a file's content."""
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def local_files(plugin_root):
    """Installed plugin files (relative, '/'-separated), excluding data/bin."""
    found = []
    if not os.path.isdir(plugin_root):
        return found
    for dirpath, dirnames, filenames in os.walk(plugin_root):
        rel_dir = os.path.relpath(dirpath, plugin_root).replace(os.sep, "/")
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d not in PROTECTED]
            rel_dir = ""
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            found.append((rel_dir + "/" + name).lstrip("/"))
    return found


# ---------------------------------------------------------------- plan / apply
def check(plugin_root, repo=None, branch=None):
    """
    Compare the installed plugin with GitHub. Returns a dict:
      local_version, remote_version, changed [paths], removed [paths],
      update_available (bool), repo, branch
    """
    if not repo:
        repo, branch = repo_settings(plugin_root)
    remote = remote_files(repo, branch)
    changed = []
    for rel, sha in sorted(remote.items()):
        path = os.path.join(plugin_root, *rel.split("/"))
        if not os.path.exists(path) or git_blob_sha(path) != sha:
            changed.append(rel)
    removed = sorted(rel for rel in local_files(plugin_root) if rel not in remote)
    local_v = read_setting(plugin_root, "APP_VERSION")
    try:
        remote_v = remote_version(repo, branch)
    except UpdateError:
        remote_v = None
    return {
        "repo": repo, "branch": branch,
        "local_version": local_v, "remote_version": remote_v,
        "changed": changed, "removed": removed,
        "update_available": bool(changed or removed),
    }


def apply(plugin_root, plan, progress=None):
    """
    Download plan['changed'] and delete plan['removed'].
    progress(done, total, path) is called after each download.
    Returns the number of files written.
    """
    repo, branch = plan["repo"], plan["branch"]
    changed, removed = plan["changed"], plan["removed"]
    staging = tempfile.mkdtemp(prefix="asset_manager_update_")
    try:
        # 1) download everything first
        for i, rel in enumerate(changed, 1):
            data = _get(raw_url(repo, branch, REPO_FOLDER + rel))
            target = os.path.join(staging, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(data)
            if progress:
                progress(i, len(changed), rel)

        # 2) all downloads OK -> move into place
        os.makedirs(plugin_root, exist_ok=True)
        for rel in changed:
            src = os.path.join(staging, *rel.split("/"))
            dst = os.path.join(plugin_root, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)

        # 3) remove files that are no longer in the repository
        for rel in removed:
            if rel.split("/")[0] in PROTECTED:
                continue
            try:
                os.remove(os.path.join(plugin_root, *rel.split("/")))
            except OSError:
                pass
        _remove_empty_dirs(plugin_root)
        _clear_pycache(plugin_root)
        return len(changed)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _remove_empty_dirs(root):
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel == "." or rel.split("/")[0] in ("data", "bin"):
            continue
        if not os.listdir(dirpath):
            os.rmdir(dirpath)


def _clear_pycache(root):
    for dirpath, dirnames, _ in os.walk(root):
        for d in list(dirnames):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)
