#!/usr/bin/env python3
"""
Quick test script for Email Database API
"""
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_endpoint(endpoint, method="GET", data=None):
    """Test an API endpoint"""
    url = f"{BASE_URL}{endpoint}"
    print(f"\n🔍 Testing {method} {endpoint}")
    print("-" * 50)
    
    try:
        if method == "GET":
            response = requests.get(url)
        elif method == "POST":
            response = requests.post(url, json=data)
        
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Response: {json.dumps(result, indent=2, default=str)}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("🚀 Testing Email Database API")
    
    # Test health check
    test_endpoint("/health")
    
    # Test basic search
    test_endpoint("/search", "POST", {
        "query": "meeting",
        "limit": 3
    })
    
    # Test snippets
    test_endpoint("/snippets", "POST", {
        "limit": 3
    })
    
    # Test stats
    test_endpoint("/stats/date-range")
    
    print("\n✅ Test completed!")
