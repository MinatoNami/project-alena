import pytest
from modules.core.controller.safety import check_repo_path

def test_allowed_repo():
    check_repo_path("/Users/lionelchong/sandbox")

def test_blocked_repo():
    with pytest.raises(PermissionError):
        check_repo_path("/etc/passwd")
