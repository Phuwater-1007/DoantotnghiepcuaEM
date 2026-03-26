import requests
from bs4 import BeautifulSoup
import json

# Create a session to maintain cookies
session = requests.Session()

def test_page(url, name, session):
    """Test a page and return results"""
    try:
        response = session.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check for errors
        errors = []
        
        # Check HTTP status
        if response.status_code != 200:
            errors.append(f"HTTP {response.status_code}")
        
        # Check for JavaScript errors in console (look for error messages in HTML)
        error_divs = soup.find_all('div', class_=['error', 'alert-danger'])
        for div in error_divs:
            errors.append(f"Error div: {div.get_text(strip=True)}")
        
        # Check for template errors (Jinja2 errors)
        if '{{' in response.text or '{%' in response.text:
            # Count unrendered template tags
            unrendered = response.text.count('{{') + response.text.count('{%')
            if unrendered > 0:
                errors.append(f"Possible unrendered template tags: {unrendered}")
        
        # Check for Vietnamese diacritics rendering
        vietnamese_chars = ['á', 'à', 'ả', 'ã', 'ạ', 'ă', 'ắ', 'ằ', 'ẳ', 'ẵ', 'ặ', 
                           'â', 'ấ', 'ầ', 'ẩ', 'ẫ', 'ậ', 'đ', 'é', 'è', 'ẻ', 'ẽ', 'ẹ',
                           'ê', 'ế', 'ề', 'ể', 'ễ', 'ệ', 'í', 'ì', 'ỉ', 'ĩ', 'ị',
                           'ó', 'ò', 'ỏ', 'õ', 'ọ', 'ô', 'ố', 'ồ', 'ổ', 'ỗ', 'ộ',
                           'ơ', 'ớ', 'ờ', 'ở', 'ỡ', 'ợ', 'ú', 'ù', 'ủ', 'ũ', 'ụ',
                           'ư', 'ứ', 'ừ', 'ử', 'ữ', 'ự', 'ý', 'ỳ', 'ỷ', 'ỹ', 'ỵ']
        has_vietnamese = any(char in response.text for char in vietnamese_chars)
        
        # Get page title
        title = soup.find('title')
        title_text = title.get_text(strip=True) if title else 'No title'
        
        # Check for common elements
        has_nav = soup.find('nav') is not None
        has_main = soup.find('main') is not None or soup.find('div', class_='container') is not None
        
        return {
            'name': name,
            'url': url,
            'status': response.status_code,
            'title': title_text,
            'has_vietnamese': has_vietnamese,
            'has_nav': has_nav,
            'has_main_content': has_main,
            'errors': errors,
            'content_length': len(response.text)
        }
    except Exception as e:
        return {
            'name': name,
            'url': url,
            'status': 'ERROR',
            'errors': [str(e)],
            'title': '',
            'has_vietnamese': False,
            'has_nav': False,
            'has_main_content': False,
            'content_length': 0
        }

# Test the application
base_url = 'http://127.0.0.1:8010'
results = []

# 1. Try to access login page
print("Testing login page...")
login_result = test_page(f'{base_url}/login', 'Login Page', session)
results.append(login_result)
print(f"  Status: {login_result['status']}, Title: {login_result['title']}")

# 2. Login
print("\nLogging in with admin/admin123...")
try:
    login_response = session.post(f'{base_url}/login', 
                                   data={'username': 'admin', 'password': 'admin123'},
                                   allow_redirects=False,
                                   timeout=10)
    print(f"  Login response: {login_response.status_code}")
    if login_response.status_code in [302, 303]:
        print("  Login successful (redirect)")
    else:
        print(f"  Login may have failed: {login_response.status_code}")
except Exception as e:
    print(f"  Login error: {e}")

# 3. Test /dashboard
print("\nTesting /dashboard...")
dashboard_result = test_page(f'{base_url}/dashboard', 'Dashboard', session)
results.append(dashboard_result)
print(f"  Status: {dashboard_result['status']}, Title: {dashboard_result['title']}")
print(f"  Vietnamese text: {dashboard_result['has_vietnamese']}")
print(f"  Errors: {dashboard_result['errors']}")

# 4. Test /monitoring
print("\nTesting /monitoring...")
monitoring_result = test_page(f'{base_url}/monitoring', 'Monitoring', session)
results.append(monitoring_result)
print(f"  Status: {monitoring_result['status']}, Title: {monitoring_result['title']}")
print(f"  Vietnamese text: {monitoring_result['has_vietnamese']}")
print(f"  Errors: {monitoring_result['errors']}")

# Get detailed monitoring page content
try:
    monitoring_response = session.get(f'{base_url}/monitoring', timeout=10)
    monitoring_soup = BeautifulSoup(monitoring_response.text, 'html.parser')
    
    # Check for specific panels
    video_panel = monitoring_soup.find('div', id='selected-video-panel')
    result_panel = monitoring_soup.find('div', id='latest-result-panel')
    
    print(f"  Selected video panel exists: {video_panel is not None}")
    print(f"  Latest result panel exists: {result_panel is not None}")
    
    # Check for video list
    video_items = monitoring_soup.find_all('div', class_='video-item')
    print(f"  Number of video items found: {len(video_items)}")
    
except Exception as e:
    print(f"  Error checking monitoring details: {e}")

# 5. Test /sources
print("\nTesting /sources...")
sources_result = test_page(f'{base_url}/sources', 'Sources', session)
results.append(sources_result)
print(f"  Status: {sources_result['status']}, Title: {sources_result['title']}")
print(f"  Errors: {sources_result['errors']}")

# Get detailed sources page content
try:
    sources_response = session.get(f'{base_url}/sources', timeout=10)
    sources_soup = BeautifulSoup(sources_response.text, 'html.parser')
    
    # Check for library layout
    library_section = sources_soup.find('section', class_='library') or sources_soup.find('div', class_='library')
    print(f"  Library section exists: {library_section is not None}")
    
    # Check for video cards
    video_cards = sources_soup.find_all('div', class_=['video-card', 'card'])
    print(f"  Number of video cards found: {len(video_cards)}")
    
except Exception as e:
    print(f"  Error checking sources details: {e}")

# Summary
print("\n" + "="*60)
print("TEST SUMMARY")
print("="*60)
for result in results:
    print(f"\n{result['name']} ({result['url']}):")
    print(f"  HTTP Status: {result['status']}")
    print(f"  Title: {result['title']}")
    print(f"  Has Vietnamese: {result['has_vietnamese']}")
    print(f"  Has Navigation: {result['has_nav']}")
    print(f"  Has Main Content: {result['has_main_content']}")
    print(f"  Content Length: {result['content_length']} bytes")
    if result['errors']:
        print(f"  ERRORS: {', '.join(result['errors'])}")
    else:
        print(f"  No errors detected")

print("\n" + "="*60)
print("All tests completed!")
