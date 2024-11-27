import os
from pybuildkite.buildkite import Buildkite


def get_token():
    token = os.environ.get("BUILDKITE_ACCESS_TOKEN")
    if token is None:
        raise ValueError("BUILDKITE_ACCESS_TOKEN environment variable not set")
    return token


def main(token: str):
    buildkite = Buildkite()
    buildkite.set_access_token(token)


if __name__ == "__main__":
    main(get_token())
