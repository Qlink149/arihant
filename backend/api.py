# Vercel entrypoint.
# Lives at backend root alongside requirements.txt so @vercel/python
# installs dependencies correctly before importing the FastAPI app.
from app.main import app  # noqa: F401
