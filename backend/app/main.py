from fastapi import FastAPI

app = FastAPI(title="Accessibility Audit Agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
