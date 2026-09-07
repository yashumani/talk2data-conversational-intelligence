from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def install_web_assets(app: FastAPI, directory: Path | None) -> None:
    if directory is None:
        return
    if not directory.joinpath("index.html").is_file():
        raise ValueError("T2D_WEB_DIRECTORY must contain a built React workspace index.html.")
    app.mount("/workspace", StaticFiles(directory=directory, html=True), name="workspace")
