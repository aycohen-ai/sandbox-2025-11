"""Unit tests for the pullrequest prartifact module

The GitHub API is mocked with the responses library, which also intercepts the
calls PyGithub makes (PyGithub rides a plain requests session). PyGithub always
addresses api.github.com with an explicit :443 port, so the mocked URLs use the
same wire format.
"""

import pytest
import responses

from pullrequest import prartifact

repo_full_name = "acme/repo"
# URL the callers hand to the prartifact functions
pr_api_url = f"https://api.github.com/repos/{repo_full_name}/pulls/1"
# URLs PyGithub actually puts on the wire
repo_wire_url = f"https://api.github.com:443/repos/{repo_full_name}"
pr_wire_url = f"{repo_wire_url}/pulls/1"
files_wire_url = f"{pr_wire_url}/files"

repo_data = {
    "full_name": repo_full_name,
    "url": f"https://api.github.com/repos/{repo_full_name}",
}
pr_data = {"number": 1, "url": pr_api_url}


def mock_pr_files(files):
    """Mock the GitHub API endpoints queried when listing the files of a PR"""
    responses.get(repo_wire_url, json=repo_data)
    responses.get(pr_wire_url, json=pr_data)
    responses.get(files_wire_url, json=files)


@responses.activate
def test_get_modified_files_returns_all_filenames():
    """Files with any status (added, modified, removed) are all returned

    The prartifact callers rely on removed files being part of the list.
    """
    mock_pr_files(
        [
            {
                "filename": "charts/partners/acme/awesome/1.0.0/report.yaml",
                "status": "added",
            },
            {"filename": "charts/partners/acme/awesome/OWNERS", "status": "modified"},
            {
                "filename": "charts/partners/acme/awesome/0.9.0/report.yaml",
                "status": "removed",
            },
        ]
    )

    assert prartifact.get_modified_files(pr_api_url) == [
        "charts/partners/acme/awesome/1.0.0/report.yaml",
        "charts/partners/acme/awesome/OWNERS",
        "charts/partners/acme/awesome/0.9.0/report.yaml",
    ]


@responses.activate
def test_get_modified_files_exits_on_github_error():
    """A GitHub API error fails the run, as before"""
    responses.get(repo_wire_url, json=repo_data)
    responses.get(pr_wire_url, json=pr_data)
    responses.get(files_wire_url, json={"message": "Not Found"}, status=404)

    with pytest.raises(SystemExit):
        prartifact.get_modified_files(pr_api_url)


@responses.activate
def test_get_pr_files_returns_file_objects_with_status():
    """Each file exposes its status, so callers can tell added from modified"""
    mock_pr_files(
        [
            {"filename": "charts/partners/acme/awesome/OWNERS", "status": "added"},
            {
                "filename": "charts/partners/acme/awesome/1.0.0/report.yaml",
                "status": "modified",
            },
        ]
    )

    files = prartifact.get_pr_files(prartifact.get_pull_request(pr_api_url))

    assert [file.filename for file in files] == [
        "charts/partners/acme/awesome/OWNERS",
        "charts/partners/acme/awesome/1.0.0/report.yaml",
    ]
    assert [file.status for file in files] == ["added", "modified"]


@responses.activate
def test_get_pull_request_fetches_repository_and_pull():
    """The owner, repository and PR number are extracted from the API URL

    Resolving the PR fetches the repository and the PR itself; its files are
    only fetched when get_pr_files is called.
    """
    mock_pr_files([{"filename": "a.yaml", "status": "added"}])

    pr = prartifact.get_pull_request(pr_api_url)

    assert [call.request.url.split("?")[0] for call in responses.calls] == [
        repo_wire_url,
        pr_wire_url,
    ]
    assert pr.url == pr_api_url


def test_get_pull_request_rejects_non_api_url():
    """URLs that are not pull request API URLs are rejected explicitly"""
    with pytest.raises(ValueError):
        prartifact.get_pull_request("https://github.com/acme/repo/pull/1")


@responses.activate
def test_get_pr_files_follows_pagination():
    """PRs spanning several pages of files are listed completely"""
    responses.get(repo_wire_url, json=repo_data)
    responses.get(pr_wire_url, json=pr_data)
    responses.get(
        files_wire_url,
        json=[{"filename": "page1.yaml", "status": "added"}],
        headers={"Link": f'<{pr_api_url}/files/page2>; rel="next"'},
    )
    responses.get(
        f"{files_wire_url}/page2",
        json=[{"filename": "page2.yaml", "status": "modified"}],
    )

    files = prartifact.get_pr_files(prartifact.get_pull_request(pr_api_url))

    assert [file.filename for file in files] == ["page1.yaml", "page2.yaml"]
