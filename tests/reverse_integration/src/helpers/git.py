"""Git utilities for cloning and managing repositories."""

from __future__ import annotations

import json
import subprocess
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class CloneResult:
    """Result of a git clone operation."""

    path: Path
    ref: str
    commit_sha: str


def clone_repo(
    url: str,
    dest: Path,
    ref: str = "main",
    auth_token: str | None = None,
) -> CloneResult:
    """Clone a git repository to a destination directory.

    Args:
        url: The repository URL (https://github.com/owner/repo)
        dest: Destination directory to clone into
        ref: Git ref to checkout (branch, tag, or commit SHA)
        auth_token: Optional authentication token for private repos

    Returns:
        CloneResult with path, ref, and commit SHA

    Raises:
        subprocess.CalledProcessError: If git commands fail
    """
    clone_url = url
    if auth_token:
        # Insert token into URL for authentication
        # https://github.com/... -> https://token@github.com/...
        clone_url = url.replace("https://", f"https://{auth_token}@")

    # Clone the repository
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, clone_url, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )

    # Get the commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=dest,
        check=True,
        capture_output=True,
        text=True,
    )
    commit_sha = result.stdout.strip()

    return CloneResult(path=dest, ref=ref, commit_sha=commit_sha)


def get_latest_release_tag(url: str, auth_token: str | None = None) -> str | None:
    """Get the latest release tag from a GitHub repository.

    Args:
        url: The repository URL (https://github.com/owner/repo)
        auth_token: Optional authentication token for private repos

    Returns:
        The tag name of the latest release, or None if no releases exist

    Raises:
        urllib.error.URLError: If the API request fails
    """
    # Extract owner/repo from URL
    # https://github.com/owner/repo -> owner/repo
    parts = url.rstrip("/").split("/")
    owner, repo = parts[-2], parts[-1]

    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

    request = urllib.request.Request(api_url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")

    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
            return data.get("tag_name")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # No releases found
            return None
        raise


def clone_at_ref(
    url: str,
    dest: Path,
    ref: str | None = None,
    use_latest_release: bool = False,
    auth_token: str | None = None,
) -> CloneResult:
    """Clone a repository at a specific ref, with support for latest release.

    Args:
        url: The repository URL
        dest: Destination directory
        ref: Explicit git ref (takes precedence over use_latest_release)
        use_latest_release: If True and ref is None, use latest release tag
        auth_token: Optional authentication token

    Returns:
        CloneResult with path, ref, and commit SHA

    Raises:
        ValueError: If use_latest_release is True but no releases exist
    """
    if ref is None and use_latest_release:
        ref = get_latest_release_tag(url, auth_token)
        if ref is None:
            raise ValueError(f"No releases found for {url}")

    return clone_repo(url, dest, ref or "main", auth_token)
