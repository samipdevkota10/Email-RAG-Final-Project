from locust import HttpUser, task, between

class MailLensUser(HttpUser):
    wait_time = between(0.1, 1.0)   # think-time between requests
    host = "http://localhost:8000"

    @task(3)
    def search_keyword(self):
        self.client.post("/search", json={
            "query": "holiday sale",
            "limit": 10,
            "offset": 0,
            "include_body": False
        })

    @task(2)
    def search_vector(self):
        self.client.post("/search/vector", json={
            "query": "summer campaign",
            "limit": 10,
            "offset": 0
        })

    @task(1)
    def chat_answer(self):
        self.client.post("/chat/answer", json={
            "query": "What are current denim trends?",
            "mode": "hybrid",
            "limit": 5,
            "offset": 0
        })

    @task(1)
    def health(self):
        self.client.get("/health")