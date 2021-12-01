from __future__ import annotations

__all__: typing.Sequence[str] = ["create_auth"]

import pathlib
import typing

import zmq.auth


def create_auth() -> None:
    pathlib.Path(".curve").mkdir(exist_ok=True)
    zmq.auth.create_certificates(".curve", "server")
    zmq.auth.create_certificates(".curve", "client")


if __name__ == "__main__":
    create_auth()
