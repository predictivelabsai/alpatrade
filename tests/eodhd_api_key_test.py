#!/usr/bin/env python3
"""
EODHD API Key Validation Test

Tests whether the EODHD API key in .env is valid and working.
"""

import os
import sys
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

def test_eodhd_api_key():
    """Test EODHD API key validity"""
    
    api_key = os.getenv('EODHD_API_KEY')
    
    if not api_key:
        print("❌ FAILED: EODHD_API_KEY not found in .env file")
        return False
    
    print(f"✓ Found EODHD_API_KEY: {api_key[:10]}...{api_key[-4:]}")
    
    # Test with a simple API call
    test_symbol = 'AAPL'
    url = f"https://eodhd.com/api/eod/{test_symbol}.US"
    params = {
        'api_token': api_key,
        'fmt': 'json',
        'limit': 1
    }
    
    print(f"\nTesting API call to: {url}")
    print(f"Symbol: {test_symbol}")
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            if data:
                print(f"✅ SUCCESS: API key is valid!")
                print(f"Sample data received: {len(data)} records")
                if isinstance(data, list) and len(data) > 0:
                    print(f"Latest data point: {data[0]}")
                return True
            else:
                print("⚠️  WARNING: API returned empty data")
                return False
        elif response.status_code == 401:
            print("❌ FAILED: 401 Unauthorized - API key is invalid or expired")
            print(f"Response: {response.text[:200]}")
            return False
        elif response.status_code == 403:
            print("❌ FAILED: 403 Forbidden - API key doesn't have permission for this endpoint")
            print(f"Response: {response.text[:200]}")
            return False
        else:
            print(f"❌ FAILED: Unexpected status code {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ FAILED: Request timed out")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED: Request error: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ FAILED: Unexpected error: {str(e)}")
        return False


def test_real_time_endpoint():
    """Test real-time price endpoint"""
    
    api_key = os.getenv('EODHD_API_KEY')
    
    if not api_key:
        return False
    
    test_symbol = 'AAPL'
    url = f"https://eodhd.com/api/real-time/{test_symbol}.US"
    params = {
        'api_token': api_key,
        'fmt': 'json'
    }
    
    print(f"\n\nTesting real-time endpoint...")
    print(f"URL: {url}")
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ SUCCESS: Real-time endpoint working!")
            print(f"Sample data: {data}")
            return True
        else:
            print(f"❌ FAILED: Status {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return False
            
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        return False


if __name__ == '__main__':
    print("="*60)
    print("EODHD API Key Validation Test")
    print("="*60)
    
    # Test historical data endpoint
    historical_ok = test_eodhd_api_key()
    
    # Test real-time endpoint
    realtime_ok = test_real_time_endpoint()
    
    print("\n" + "="*60)
    print("Test Summary:")
    print("="*60)
    print(f"Historical Data Endpoint: {'✅ PASS' if historical_ok else '❌ FAIL'}")
    print(f"Real-Time Data Endpoint:  {'✅ PASS' if realtime_ok else '❌ FAIL'}")
    
    if historical_ok and realtime_ok:
        print("\n✅ All tests passed! EODHD API key is valid and working.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please check your EODHD API key in .env file.")
        print("\nTo fix:")
        print("1. Check if your API key is correct")
        print("2. Verify your subscription is active at https://eodhd.com")
        print("3. Make sure the key has access to the endpoints you're using")
        sys.exit(1)
