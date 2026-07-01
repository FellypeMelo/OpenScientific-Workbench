from locust import HttpUser, task, between
import uuid

class OSWGatewayUser(HttpUser):
    wait_time = between(1, 3)

    @task(2)
    def test_session_lifecycle(self):
        user_id = str(uuid.uuid4())
        workspace_id = str(uuid.uuid4())
        
        # 1. Create session
        headers = {"Content-Type": "application/json"}
        payload = {"user_id": user_id, "workspace_id": workspace_id}
        
        response = self.client.post("/api/v1/sessions", json=payload, headers=headers)
        if response.status_code == 201:
            session_data = response.json()
            session_id = session_data["id"]
            
            # 2. Query chat endpoint
            self.client.post(
                f"/api/v1/sessions/{session_id}/chat",
                json={"prompt": "Predict protein folding topology"},
                headers=headers
            )
            
            # 3. Retrieve session status
            self.client.get(f"/api/v1/sessions/{session_id}")
