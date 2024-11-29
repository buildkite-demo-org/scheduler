import time
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple

from github import Github, GithubIntegration, CheckRun
import datetime

from github.GithubException import GithubException
from github.CheckSuite import CheckSuite
from github.GithubObject import NotSet
from github.Installation import Installation
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest
from github.PullRequestMergeStatus import PullRequestMergeStatus
from github.Repository import Repository
import requests

from constants import GITHUB_APP_ID

PRIVATE_KEY_PATH = Path("github_app_private_key.pem").resolve()


class Pipeline(str, Enum):
    CHECK = "check"
    GATE = "gate"


class CheckRunOutput(Dict[str, str], Enum):
    PENDING_CHECK = {"title": "Check is running", "summary": "..."}
    PENDING_GATE = {"title": "Gate is running", "summary": "..."}
    SUCCESSFUL_CHECK = {
        "title": "Build Results",
        "summary": "Check completed successfully.",
    }
    SUCCESSFUL_GATE = {
        "title": "Build Results",
        "summary": "Gate completed successfully.",
    }
    FAILED_CHECK = {"title": "Build Results", "summary": "Check failed."}
    FAILED_GATE = {"title": "Build Results", "summary": "Gate failed."}

    CANCELED_CHECK = {"title": "Build Results", "summary": "Check canceled."}
    CANCELED_GATE = {"title": "Build Results", "summary": "Gate canceled."}


class CheckRunConclusion(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"


class CheckRunStatus(str, Enum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"


class GitHubConnector:
    def __init__(self):
        self.graphql_url = "https://api.github.com/graphql"
        self.installation: Installation = self.fetch_installation()
        private_key: str = self.read_private_key(PRIVATE_KEY_PATH)
        self.github = self.authenticate_as_github_app(
            GITHUB_APP_ID, self.installation.id, private_key
        )
        self.pr_id_to_check_run_id_dict: Dict[
            (str, str, int), int
        ] = {}  # (repo_name, check_name, pr_number) -> check_run_id

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
        repo_name: str,
        check_name: Pipeline,
        pull_request_number: int,
        status: CheckRunStatus,
        conclusion: CheckRunConclusion | None = None,
        completed_at: datetime.datetime | None = None,
        output: CheckRunOutput | None = None,
    ):
        repo: Repository = self.github.get_repo(repo_name)
        head_sha: str = self.get_head_commit_sha_for_pull_request(
            repo, pull_request_number
        )
        check_run_tuple: Tuple[str, str, int] = (
            repo_name,
            check_name,
            pull_request_number,
        )

        if check_run_tuple in self.pr_id_to_check_run_id_dict.keys():
            check_run_id: int = self.pr_id_to_check_run_id_dict[check_run_tuple]
            self.edit_checks_page(
                repository=repo,
                check_run_id=check_run_id,
                status=status,
                conclusion=conclusion,
                completed_at=completed_at,
                output=output,
            )

            if conclusion and completed_at:
                del self.pr_id_to_check_run_id_dict[check_run_tuple]

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
        conclusion: str | None = None,
        completed_at: datetime.datetime | None = None,
        output: Dict | None = None,
    ):
        completed_at = completed_at or NotSet
        conclusion = conclusion or NotSet
        check_run: CheckRun = repository.get_check_run(check_run_id)
        check_run.edit(
            name=check_run.name,
            head_sha=check_run.head_sha,
            details_url=check_run.details_url,
            external_id=check_run.external_id,
            status=status,
            started_at=check_run.started_at,
            conclusion=conclusion,
            completed_at=completed_at,
            output=output,
        )
        check_run.update()

    def attempt_merge(self, repo_name: str, pr_number: int) -> bool:
        repo: Repository = self.github.get_repo(repo_name)
        pull_request: PullRequest = repo.get_pull(pr_number)

        if pull_request.mergeable:
            # Please don't look at this
            try:
                pull_request.merge()
                return True
            except GithubException:
                self.enqueue_pull_request(pull_request.node_id)
                return True
        return False

    def enqueue_pull_request(self, pull_request_id: str):
        graphql_query = """
        mutation {
            enqueuePullRequest(input: {pullRequestId: "%s"}){
                clientMutationId
                mergeQueueEntry {
                    id
                    pullRequest {
                        title
                        number
                    }
                }
            }
        }
        """
        query = {"query": graphql_query % pull_request_id}
        headers = {"Authorization": f"bearer %s" % self.github.requester.auth.token}
        response = requests.post(
            url=self.graphql_url,
            json=query,
            headers=headers,
        )
        response.raise_for_status()


# Main function to be called with the necessary parameters
def demo_github_connector():
    github = GitHubConnector()
    repo_name = "buildkite-demo-org/scheduler"  # Replace with your repository name

    # Check
    github.update_checks_page(
        repo_name=repo_name,
        check_name=Pipeline.CHECK,
        pull_request_number=3,
        status=CheckRunStatus.IN_PROGRESS,
        conclusion=None,
        output=CheckRunOutput.PENDING_CHECK,
    )

    time.sleep(5)

    github.update_checks_page(
        repo_name=repo_name,
        check_name=Pipeline.CHECK,
        pull_request_number=3,
        status=CheckRunStatus.COMPLETED,
        conclusion=CheckRunConclusion.SUCCESS,
        output=CheckRunOutput.SUCCESSFUL_CHECK,
    )

    time.sleep(1)

    # Gate
    github.update_checks_page(
        repo_name=repo_name,
        check_name=Pipeline.GATE,
        pull_request_number=3,
        status=CheckRunStatus.IN_PROGRESS,
        conclusion=None,
        output=CheckRunOutput.PENDING_GATE,
    )

    time.sleep(5)

    github.update_checks_page(
        repo_name=repo_name,
        check_name=Pipeline.GATE,
        pull_request_number=3,
        status=CheckRunStatus.COMPLETED,
        conclusion=CheckRunConclusion.FAILURE,
        output=CheckRunOutput.FAILED_GATE,
    )


if __name__ == "__main__":
    demo_github_connector()
