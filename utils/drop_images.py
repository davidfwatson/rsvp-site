#!/usr/bin/python3
import re

def strip_base64_images(html_content):
    # This regex matches <img> tags with base64 encoded images
    base64_image_pattern = r'<img[^>]*src="data:image\/[^;]+;base64[^"]*"[^>]*>'
    
    # Use re.sub to remove the matching base64 image tags
    stripped_html = re.sub(base64_image_pattern, '', html_content)
    
    return stripped_html

# Example usage
html_content = """

"""

stripped_html = strip_base64_images(html_content)
print(stripped_html)
