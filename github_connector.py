import time
from pathlib import Path
from typing import Dict, Tuple

from github import Github, GithubIntegration, CheckRun
import datetime

from github.Installation import Installation
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest
from github.Repository import Repository

from constants import GITHUB_APP_ID

# Constants
PRIVATE_KEY_PATH = Path("github_app_private_key.pem").resolve()


class GitHubConnector:
    def __init__(self):
        self.installation: Installation = self.fetch_installation()
        private_key: str = self.read_private_key(PRIVATE_KEY_PATH)
        self.github = self.authenticate_as_github_app(
            GITHUB_APP_ID, self.installation.id, private_key
        )
        self.pr_id_to_check_run_id_dict: Dict[
            (int, str), int
        ] = {}  # (pr_id, check_name) -> check_run_id

    @staticmethod
    def read_private_key(private_key_path: Path) -> str:
        with open(private_key_path, "r") as file:
            return file.read()

    @classmethod
    def fetch_installation(cls) -> Installation:
        integration: GithubIntegration = GithubIntegration(
            GITHUB_APP_ID, cls.read_private_key(PRIVATE_KEY_PATH)
        )
        installations: PaginatedList[Installation] = integration.get_installations()
        for installation in installations:
            return installation

    @staticmethod
    def authenticate_as_github_app(app_id, installation_id, private_key):
        integration = GithubIntegration(app_id, private_key)
        installation_access_token = integration.get_access_token(installation_id)
        return Github(installation_access_token.token)

    @staticmethod
    def get_head_commit_sha_for_pull_request(
        repo: Repository, pull_request_id: int
    ) -> str:
        pull_request: PullRequest = repo.get_pull(pull_request_id)
        return pull_request.head.sha

    def update_checks_page(
        self,
        repo_name,
        check_name,
        pull_request_id,
        status,
        conclusion=None,
        output=None,
    ):
        repo: Repository = self.github.get_repo(repo_name)
        head_sha: str = self.get_head_commit_sha_for_pull_request(repo, pull_request_id)
        check_run_tuple: Tuple[int, str] = (pull_request_id, check_name)

        if check_run_tuple in self.pr_id_to_check_run_id_dict.keys():
            check_run_id: int = self.pr_id_to_check_run_id_dict[check_run_tuple]
            self.edit_checks_page(
                repository=repo,
                check_run_id=check_run_id,
                status=status,
                conclusion=conclusion,
                output=output,
            )
        else:
            check_run_id: int = self.init_checks_page(
                repository=repo,
                check_name=check_name,
                commit_sha=head_sha,
                status=status,
                output=output,
            )
            self.pr_id_to_check_run_id_dict[check_run_tuple] = check_run_id

    @staticmethod
    def init_checks_page(
        repository: Repository,
        check_name: str,
        commit_sha: str,
        status: str,
        output: Dict,
    ) -> int:
        check_run: CheckRun = repository.create_check_run(
            name=check_name,
            head_sha=commit_sha,
            status=status,
            started_at=datetime.datetime.utcnow(),
            output=output,
        )
        check_run.update()
        return check_run.id

    @staticmethod
    def edit_checks_page(
        repository: Repository,
        check_run_id: int,
        status: str,
        conclusion: str,
        output: Dict,
    ):
        check_run: CheckRun = repository.get_check_run(check_run_id)
        check_run.edit(
            name=check_run.name,
            head_sha=check_run.head_sha,
            details_url=check_run.details_url,
            external_id=check_run.external_id,
            status=status,
            started_at=check_run.started_at,
            conclusion=conclusion,
            completed_at=datetime.datetime.utcnow(),
            output=output,
        )
        check_run.update()


# Main function to be called with the necessary parameters
def demo_github_connector():
    github = GitHubConnector()
    repo_name = "buildkite-demo-org/scheduler"  # Replace with your repository name

    # Check
    output = {"title": "Check is running", "summary": "..."}
    github.update_checks_page(
        repo_name=repo_name,
        check_name="check",
        pull_request_id=3,
        status="in_progress",
        conclusion=None,
        output=output,
    )

    time.sleep(5)

    build_successful = True
    output = {
        "title": "Build Results",
        "summary": "The build completed successfully."
        if build_successful
        else "The build failed.",
    }
    conclusion = "success" if build_successful else "failure"
    github.update_checks_page(
        repo_name=repo_name,
        check_name="check",
        pull_request_id=3,
        status="completed",
        conclusion=conclusion,
        output=output,
    )

    time.sleep(1)

    # Gate
    output = {"title": "Gate is running", "summary": "..."}
    github.update_checks_page(
        repo_name=repo_name,
        check_name="gate",
        pull_request_id=3,
        status="in_progress",
        conclusion=None,
        output=output,
    )

    time.sleep(5)

    build_successful = False
    output = {
        "title": "Build Results",
        "summary": "The build completed successfully."
        if build_successful
        else "The build failed.",
    }
    conclusion = "success" if build_successful else "failure"
    github.update_checks_page(
        repo_name=repo_name,
        check_name="gate",
        pull_request_id=3,
        status="completed",
        conclusion=conclusion,
        output=output,
    )


if __name__ == "__main__":
    demo_github_connector()
