import os
from pybuildkite.buildkite import Buildkite
from flask import Flask, request

app = Flask(__name__)


def get_token():
    token = os.environ.get("BUILDKITE_ACCESS_TOKEN")
    if token is None:
        raise ValueError("BUILDKITE_ACCESS_TOKEN environment variable not set")
    return token


def main(token: str):
    buildkite = Buildkite()
    buildkite.set_access_token(token)


@app.route("/webhooks", methods=["POST"])
def entrypoint():
    main(get_token())
    return "OK"


if __name__ == "__main__":
    app.run()
