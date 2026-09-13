if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:criar_aplicacao",
        host="127.0.0.1",
        port=8000,
        reload=True,
        factory=True,
        log_config="logging.json",
    )
