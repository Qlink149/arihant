# Vercel entrypoint — imports the FastAPI app from the package.
# requirements.txt lives next to this file, so @vercel/python finds it.
from app.main import app  # noqa: F401
