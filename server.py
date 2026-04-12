from fastapi import FastAPI

app = FastAPI()

@app.get("/hello")
def hello():
    return {"message": "Hello World"}

@app.get("/solve")
def solve_api(x: int):
    return {"result": x * 2}