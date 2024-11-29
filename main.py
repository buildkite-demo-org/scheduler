import os
import datetime
from typing import Dict, Any, Optional, Set, List

from pybuildkite import buildkite
from pybuildkite.buildkite import Buildkite
from flask import Flask, request
from dotenv import load_dotenv
from pybuildkite.pipelines import Pipelines

from constants import BUILDKITE_ORGANISATION, BAZEL_BUILD_PIPELINE
from github_connector import CheckRunConclusion, GitHubConnector, CheckRunStatus, Pipeline, CheckRunOutput

app = Flask(__name__)


def get_token():
    load_dotenv()
    token = os.environ.get("BUILDKITE_ACCESS_TOKEN")
    if token is None:
        raise ValueError("BUILDKITE_ACCESS_TOKEN environment variable not set")
    return token


def setup_buildkite(token: str) -> Buildkite:
    buildkite = Buildkite()
    buildkite.set_access_token(token)
    return buildkite


BUILDKITE: Buildkite = setup_buildkite(get_token())
GITHUB_CONNECTOR: GitHubConnector = GitHubConnector()
BUILDS = {}


def is_pull_request_changed(action: str) -> bool:
    return action in ["opened", "reopened", "synchronize"]


def generate_build_message_from_payload(pr_json_payload: Dict[str, Any]) -> str:
    pr_nr: int = int(pr_json_payload["pull_request"]["number"])
    return f"Build for Pull Request: {pr_nr}"


def extract_branch_name_from_payload(pr_json_payload: Dict[str, Any]) -> str:
    return pr_json_payload["pull_request"]["head"]["ref"]


def fetch_repo_pipelines(repo_full_name: str) -> Set[str]:
    pipelines: Pipelines = BUILDKITE.pipelines().list_pipelines(BUILDKITE_ORGANISATION)
    return set([pipeline["slug"] for pipeline in pipelines if repo_full_name in pipeline["repository"]])


def trigger_build(
        buildkite: Buildkite, repository_name: str, commit_sha: str, branch: str, build_message: str
) -> List[Any]:
    pipeline_set: Set[str] = fetch_repo_pipelines(repository_name)
    build_list: List[Any] = []

    try:

        pipeline: str
        for pipeline in pipeline_set:
            build_list.append(buildkite.builds().create_build(
                BUILDKITE_ORGANISATION,
                pipeline,
                commit_sha,
                branch,
                clean_checkout=True,
                message=build_message,
                ignore_pipeline_branch_filters=True
            ))

        return build_list

    except Exception as error:
        print(error)
        raise error


def extract_repository_name(pr_json_payload: Dict[str, Any]) -> str:
    return pr_json_payload["repository"]["full_name"]


def extract_pr_number(pr_json_payload: Dict[str, Any]) -> int:
    return int(pr_json_payload["number"])


def handle_pull_requests(pr_json_payload: Dict[str, Any]) -> None:
    action: str = pr_json_payload["action"]
    repository_name: str = extract_repository_name(pr_json_payload)
    pull_request_number: int = extract_pr_number(pr_json_payload)

    if is_pull_request_changed(action):
        GITHUB_CONNECTOR.update_checks_page(
            repo_name=repository_name,
            check_name=Pipeline.CHECK,
            pull_request_number=pull_request_number,
            status=CheckRunStatus.QUEUED,
            output=CheckRunOutput.PENDING_CHECK,
        )
        build_message: str = generate_build_message_from_payload(pr_json_payload)
        branch: str = extract_branch_name_from_payload(pr_json_payload)
        build_list: List[Any] = trigger_build(
            BUILDKITE, repository_name=repository_name, commit_sha="HEAD", branch=branch, build_message=build_message
        )

        for build in build_list:
            BUILDS[build["id"]] = (build, pr_json_payload)


def handle_check_run(check_run_payload: Dict[str, Any]) -> None:
    action: str = check_run_payload["action"]
    pipeline: str = check_run_payload["check_run"]["name"]
    conclusion: str = check_run_payload["check_run"]["conclusion"]

    if action == CheckRunStatus.COMPLETED and pipeline == Pipeline.CHECK and conclusion == CheckRunConclusion.SUCCESS:
        repo_name: str = check_run_payload["repository"]["full_name"]
        if not check_run_payload["check_run"]["pull_requests"]:
            print("No pull request found for check run!")
            return

        pr_number: int = int(check_run_payload["check_run"]["pull_requests"][0]["number"])

        if GITHUB_CONNECTOR.attempt_merge(repo_name=repo_name, pr_number=pr_number):
            print(f"Pull Request: #{pr_number} was merged!")

def handle_check_suite(check_suite_payload: Dict[str, Any]) -> None:
    action: str = check_suite_payload["action"]
    app: str = check_suite_payload["check_suite"]["app"]["slug"]
    
    if action == "requested" and app == "buildkite-scheduler":
        repository_name: str = check_suite_payload["repository"]["full_name"]
        branch: str = check_suite_payload["check_suite"]["head_branch"]
        sha: str = check_suite_payload["check_suite"]["head_sha"]
        message: str = check_suite_payload["check_suite"]["head_commit"]["message"]
    
        build_list: List[Any] = trigger_build(BUILDKITE, repository_name=repository_name, commit_sha=sha, branch=branch, build_message=message)
        
        # TODO: fill global builds with new build
        # for build in build_list:
        #     BUILDS[build["id"]] = (build, pr_json_payload)



@app.route("/github_webhooks", methods=["POST"])
def github_entrypoint():
    payload: Dict[str, Any] = request.get_json()
    request_header: Optional[str] = request.headers.get("X-GitHub-Event")

    if request_header == "pull_request":
        handle_pull_requests(payload)

    if request_header == "check_run":
        handle_check_run(payload)
        
    if request_header == "check_suite":
        handle_check_suite(payload)

    return "OK"


def handle_build_running(payload: Dict[str, Any]):
    build_id = payload["build"]["id"]

    if build_id in BUILDS:
        print(f"Build {build_id} running!")
        _, pull_request = BUILDS[build_id]
        repository = pull_request["repository"]["full_name"]
        check_name = Pipeline.CHECK
        pr_number = pull_request["number"]
        status = CheckRunStatus.IN_PROGRESS
        # output = CheckRunOutput.PENDING_CHECK
        GITHUB_CONNECTOR.update_checks_page(
            repo_name=repository,
            check_name=check_name,
            pull_request_number=pr_number,
            status=status,
            conclusion=None,
            completed_at=None,
            output={"title": "Check is running", "summary": f"Build URL: {payload["build"]["web_url"]}"},
        )


def handle_build_finished(payload: Dict[str, Any]):
    build_id = payload["build"]["id"]
    build_result = payload["build"]["state"]

    if build_result == "passed":
        conclusion = CheckRunConclusion.SUCCESS
        output = CheckRunOutput.SUCCESSFUL_CHECK

    elif build_result == "canceled":
        conclusion = CheckRunConclusion.CANCELLED
        output = CheckRunOutput.CANCELED_CHECK

    elif build_result == "failed":
        conclusion = CheckRunConclusion.FAILURE
        output = CheckRunOutput.FAILED_CHECK
    else:
        print(f"Unhandled build result {build_result}")
        return

    if build_id in BUILDS:
        print(f"Build {build_id} has finished with result {conclusion}!")
        _, pull_request = BUILDS[build_id]
        repository = pull_request["repository"]["full_name"]
        check_name = Pipeline.CHECK
        pr_number = pull_request["number"]
        status = CheckRunStatus.COMPLETED
        conclusion = conclusion
        completed_at = datetime.datetime.strptime(payload["build"]["finished_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        output = output

        GITHUB_CONNECTOR.update_checks_page(
            repo_name=repository,
            check_name=check_name,
            pull_request_number=pr_number,
            status=status,
            conclusion=conclusion,
            completed_at=completed_at,
            output=output,
        )

        del BUILDS[build_id]


def handle_build_canceled(payload: Dict[str, Any]):
    print("Not implemented!")
    pass


@app.route("/buildkite_webhooks", methods=["POST"])
def buildkite_entrypoint():
    payload: Dict[str, Any] = request.get_json()
    request_header: Optional[str] = request.headers.get("X-Buildkite-Event")

    if request_header == "build.running":
        handle_build_running(payload)

    elif request_header == "build.finished":
        handle_build_finished(payload)

    elif request_header == "build.failing":
        handle_build_canceled(payload)

    return "OK"


if __name__ == "__main__":
    app.run(port=5000, debug=True)
