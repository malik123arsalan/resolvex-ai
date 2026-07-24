from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "ResolveX API is live and working"}