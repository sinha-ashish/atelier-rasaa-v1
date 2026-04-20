#!/usr/bin/env python3
"""
Backend API Testing for RASAA Atelier Platform
Tests all API endpoints including auth, products, materials, regions, and contact
"""

import requests
import sys
import json
from datetime import datetime
from typing import Dict, Any, Optional

class RASAAAPITester:
    def __init__(self, base_url="https://cultural-bridge-24.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.session_token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        
    def log_test(self, name: str, success: bool, details: str = ""):
        """Log test results"""
        self.tests_run += 1
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name}")
        if details:
            print(f"    {details}")
        if success:
            self.tests_passed += 1
        else:
            self.failed_tests.append({"name": name, "details": details})
        print()

    def make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                    headers: Optional[Dict] = None, expected_status: int = 200) -> tuple:
        """Make HTTP request and return success status and response"""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        
        # Default headers
        req_headers = {'Content-Type': 'application/json'}
        if headers:
            req_headers.update(headers)
        
        # Add auth if available
        if self.session_token:
            req_headers['Authorization'] = f'Bearer {self.session_token}'
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=req_headers, timeout=10)
            elif method.upper() == 'POST':
                response = requests.post(url, json=data, headers=req_headers, timeout=10)
            elif method.upper() == 'PUT':
                response = requests.put(url, json=data, headers=req_headers, timeout=10)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=req_headers, timeout=10)
            else:
                return False, {"error": f"Unsupported method: {method}"}
            
            success = response.status_code == expected_status
            try:
                response_data = response.json()
            except:
                response_data = {"text": response.text, "status_code": response.status_code}
            
            return success, response_data
            
        except requests.exceptions.RequestException as e:
            return False, {"error": str(e)}

    def test_health_endpoints(self):
        """Test health and root endpoints"""
        print("🔍 Testing Health Endpoints...")
        
        # Test root endpoint
        success, data = self.make_request('GET', '/')
        self.log_test("Root endpoint (/api/)", success, 
                     f"Response: {data.get('message', 'No message')}" if success else f"Error: {data}")
        
        # Test health endpoint
        success, data = self.make_request('GET', '/health')
        self.log_test("Health endpoint (/api/health)", success,
                     f"Status: {data.get('status', 'Unknown')}" if success else f"Error: {data}")

    def test_products_endpoints(self):
        """Test products API endpoints"""
        print("🔍 Testing Products Endpoints...")
        
        # Test get all products
        success, data = self.make_request('GET', '/products')
        products_count = len(data) if success and isinstance(data, list) else 0
        self.log_test("Get all products (/api/products)", success,
                     f"Found {products_count} products" if success else f"Error: {data}")
        
        # Test category filter
        success, data = self.make_request('GET', '/products?category=jewelry')
        jewelry_count = len(data) if success and isinstance(data, list) else 0
        self.log_test("Filter products by category (/api/products?category=jewelry)", success,
                     f"Found {jewelry_count} jewelry items" if success else f"Error: {data}")
        
        # Test region filter
        success, data = self.make_request('GET', '/products?region=Rajasthan')
        rajasthan_count = len(data) if success and isinstance(data, list) else 0
        self.log_test("Filter products by region (/api/products?region=Rajasthan)", success,
                     f"Found {rajasthan_count} Rajasthan products" if success else f"Error: {data}")
        
        # Test specific product
        success, data = self.make_request('GET', '/products/prod_001')
        product_name = data.get('name', 'Unknown') if success else None
        self.log_test("Get specific product (/api/products/prod_001)", success,
                     f"Product: {product_name}" if success else f"Error: {data}")
        
        # Test non-existent product
        success, data = self.make_request('GET', '/products/nonexistent', expected_status=404)
        self.log_test("Get non-existent product (404 expected)", success,
                     "Correctly returned 404" if success else f"Unexpected response: {data}")

    def test_materials_endpoints(self):
        """Test materials API endpoints (B2B)"""
        print("🔍 Testing Materials Endpoints...")
        
        # Test get all materials
        success, data = self.make_request('GET', '/materials')
        materials_count = len(data) if success and isinstance(data, list) else 0
        self.log_test("Get all materials (/api/materials)", success,
                     f"Found {materials_count} materials" if success else f"Error: {data}")
        
        # Test category filter
        success, data = self.make_request('GET', '/materials?category=gemstones')
        gems_count = len(data) if success and isinstance(data, list) else 0
        self.log_test("Filter materials by category (/api/materials?category=gemstones)", success,
                     f"Found {gems_count} gemstones" if success else f"Error: {data}")
        
        # Test region filter
        success, data = self.make_request('GET', '/materials?region=Gujarat')
        gujarat_count = len(data) if success and isinstance(data, list) else 0
        self.log_test("Filter materials by region (/api/materials?region=Gujarat)", success,
                     f"Found {gujarat_count} Gujarat materials" if success else f"Error: {data}")
        
        # Test specific material
        success, data = self.make_request('GET', '/materials/gem_001')
        material_name = data.get('name', 'Unknown') if success else None
        self.log_test("Get specific material (/api/materials/gem_001)", success,
                     f"Material: {material_name}" if success else f"Error: {data}")

    def test_regions_endpoint(self):
        """Test regions API endpoint"""
        print("🔍 Testing Regions Endpoint...")
        
        success, data = self.make_request('GET', '/regions')
        regions_count = len(data) if success and isinstance(data, list) else 0
        self.log_test("Get all regions (/api/regions)", success,
                     f"Found {regions_count} regions" if success else f"Error: {data}")

    def test_auth_endpoints(self):
        """Test authentication endpoints"""
        print("🔍 Testing Authentication Endpoints...")
        
        # Test registration
        test_user_data = {
            "email": f"test.user.{datetime.now().strftime('%H%M%S')}@example.com",
            "password": "TestPass123!",
            "name": "Test User",
            "company": "Test Company",
            "is_b2b": False
        }
        
        success, data = self.make_request('POST', '/auth/register', data=test_user_data, expected_status=200)
        if success and 'token' in data:
            self.session_token = data['token']
            user_email = data.get('user', {}).get('email', 'Unknown')
            self.log_test("User registration (/api/auth/register)", success,
                         f"Registered user: {user_email}")
        else:
            self.log_test("User registration (/api/auth/register)", success,
                         f"Error: {data}")
        
        # Test login with same credentials
        login_data = {
            "email": test_user_data["email"],
            "password": test_user_data["password"]
        }
        
        success, data = self.make_request('POST', '/auth/login', data=login_data, expected_status=200)
        if success and 'token' in data:
            self.session_token = data['token']
            self.log_test("User login (/api/auth/login)", success,
                         f"Login successful for: {login_data['email']}")
        else:
            self.log_test("User login (/api/auth/login)", success,
                         f"Error: {data}")
        
        # Test get current user
        if self.session_token:
            success, data = self.make_request('GET', '/auth/me')
            user_name = data.get('name', 'Unknown') if success else None
            self.log_test("Get current user (/api/auth/me)", success,
                         f"User: {user_name}" if success else f"Error: {data}")
        
        # Test invalid login
        invalid_login = {
            "email": "invalid@example.com",
            "password": "wrongpassword"
        }
        success, data = self.make_request('POST', '/auth/login', data=invalid_login, expected_status=401)
        self.log_test("Invalid login (401 expected)", success,
                     "Correctly returned 401" if success else f"Unexpected response: {data}")

    def test_contact_endpoint(self):
        """Test contact form submission"""
        print("🔍 Testing Contact Endpoint...")
        
        contact_data = {
            "name": "Test Contact",
            "email": "test.contact@example.com",
            "subject": "Test Subject",
            "message": "This is a test message from the API test suite."
        }
        
        success, data = self.make_request('POST', '/contact', data=contact_data, expected_status=200)
        contact_id = data.get('contact_id', 'Unknown') if success else None
        self.log_test("Submit contact form (/api/contact)", success,
                     f"Contact ID: {contact_id}" if success else f"Error: {data}")

    def test_wholesale_request(self):
        """Test wholesale access request"""
        print("🔍 Testing Wholesale Request Endpoint...")
        
        wholesale_data = {
            "company_name": "Test Fashion House",
            "contact_name": "Test Contact",
            "email": "test.wholesale@example.com",
            "phone": "+1234567890",
            "business_type": "fashion_house",
            "message": "Test wholesale access request"
        }
        
        success, data = self.make_request('POST', '/wholesale/request', data=wholesale_data, expected_status=200)
        request_id = data.get('request_id', 'Unknown') if success else None
        self.log_test("Submit wholesale request (/api/wholesale/request)", success,
                     f"Request ID: {request_id}" if success else f"Error: {data}")

    def test_quote_request(self):
        """Test quote request (requires auth)"""
        print("🔍 Testing Quote Request Endpoint...")
        
        if not self.session_token:
            self.log_test("Quote request (requires auth)", False, "No session token available")
            return
        
        quote_data = {
            "material_id": "gem_001",
            "material_name": "Jaipur Ruby",
            "quantity": "10 carats",
            "specifications": "High quality, deep red color",
            "name": "Test Buyer",
            "email": "test.buyer@example.com",
            "company": "Test Jewelry Co",
            "phone": "+1234567890"
        }
        
        success, data = self.make_request('POST', '/quote/request', data=quote_data, expected_status=200)
        quote_id = data.get('quote_id', 'Unknown') if success else None
        self.log_test("Submit quote request (/api/quote/request)", success,
                     f"Quote ID: {quote_id}" if success else f"Error: {data}")

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting RASAA Atelier API Tests")
        print("=" * 50)
        
        # Test in logical order
        self.test_health_endpoints()
        self.test_regions_endpoint()
        self.test_products_endpoints()
        self.test_materials_endpoints()
        self.test_auth_endpoints()
        self.test_contact_endpoint()
        self.test_wholesale_request()
        self.test_quote_request()
        
        # Print summary
        print("=" * 50)
        print(f"📊 Test Summary:")
        print(f"   Total Tests: {self.tests_run}")
        print(f"   Passed: {self.tests_passed}")
        print(f"   Failed: {len(self.failed_tests)}")
        print(f"   Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        if self.failed_tests:
            print("\n❌ Failed Tests:")
            for test in self.failed_tests:
                print(f"   - {test['name']}: {test['details']}")
        
        return len(self.failed_tests) == 0

def main():
    """Main test runner"""
    tester = RASAAAPITester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())