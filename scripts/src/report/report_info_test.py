import json
import subprocess

import pytest

from report import report_info

# What chart-verifier actually writes to stdout when the report's digest does not
# match its content. Note the lowercase "digest": report_info.SHA_ERROR must keep
# matching this case-insensitively.
SHA_MISMATCH_OUTPUT = (
    "error executing command: digest in report did not match report content\n"
)


@pytest.fixture
def errors_file(tmp_path, monkeypatch):
    """Points write_error_log at a temp dir and reads back what it recorded.

    The file it writes is what ends up verbatim in the PR comment.
    """
    monkeypatch.setenv("WORKFLOW_WORKING_DIRECTORY", str(tmp_path))
    monkeypatch.delenv("VERIFIER_IMAGE", raising=False)

    def read():
        return (tmp_path / "errors").read_text()

    return read


def fake_verifier_output(monkeypatch, stdout):
    """Makes the chart-verifier subprocess return stdout."""

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(report_info.subprocess, "run", fake_run)


def test_sha_mismatch_reports_a_plain_message(monkeypatch, errors_file):
    fake_verifier_output(monkeypatch, SHA_MISMATCH_OUTPUT.encode())

    with pytest.raises(SystemExit):
        report_info.get_report_digests(report_path="report.yaml")

    assert errors_file() == f"[ERROR] {report_info.SHA_ERROR}\n"


def test_unparseable_output_does_not_leak_the_exception(monkeypatch, errors_file):
    fake_verifier_output(monkeypatch, b"not json at all")

    with pytest.raises(SystemExit):
        report_info.get_report_digests(report_path="report.yaml")

    errors = errors_file()
    assert "not json at all" in errors
    # The submitter should never see the Python exception, nor the "/n" that used
    # to be written in place of a newline. See issue #539.
    assert "JSONDecodeError" not in errors
    assert "type(err)" not in errors
    assert "/n" not in errors


def test_undecodable_output_does_not_traceback(monkeypatch, errors_file):
    fake_verifier_output(monkeypatch, b"\xff\xfe not utf-8")

    with pytest.raises(SystemExit):
        report_info.get_report_digests(report_path="report.yaml")

    assert "JSONDecodeError" not in errors_file()


def test_valid_output_is_returned(monkeypatch, errors_file):
    digests = {"chart": "sha256:abc", "package": "sha256:def"}
    fake_verifier_output(monkeypatch, json.dumps({"digests": digests}).encode())

    assert report_info.get_report_digests(report_path="report.yaml") == digests
