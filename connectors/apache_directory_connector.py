import os
import re
import urllib.parse
from datetime import datetime
from email.utils import parsedate_to_datetime
import requests
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

class ApacheDirectoryConnector:
    def __init__(self, url: str, filename_prefix: str = None):
        self.url = url
        self.filename_prefix = filename_prefix
        # Ensures URL ends with slash for relative resolving
        if not self.url.endswith('/'):
            self.url += '/'

    def crawl(self):
        """
        Crawls the Apache directory index and yields metadata about matching PDF files.
        Yields:
            dict: {
                'url': str,
                'filename': str (decoded),
                'last_modified_hint': datetime (optional, parsed from index if available)
            }
        """
        logger.info(f"Crawling directory: {self.url}")
        try:
            response = requests.get(self.url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch {self.url}: {e}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Apache indexes typically have tables or pre blocks with links.
        # Find all anchor tags pointing to PDFs.
        for a_tag in soup.find_all('a'):
            href = a_tag.get('href')
            if not href or href.startswith('?') or href.startswith('/'):
                continue
            
            # We are only interested in PDF files for this framework
            if not href.lower().endswith('.pdf'):
                continue

            decoded_filename = urllib.parse.unquote(href)

            if self.filename_prefix and not decoded_filename.lower().startswith(self.filename_prefix.lower()):
                logger.debug(f"Skipping {decoded_filename} (does not match prefix '{self.filename_prefix}')")
                continue

            file_url = urllib.parse.urljoin(self.url, href)
            
            # Try to find Last-Modified from the row if it's a standard Apache autoindex table
            last_modified = None
            parent_tr = a_tag.find_parent('tr')
            if parent_tr:
                tds = parent_tr.find_all('td')
                if len(tds) >= 3:
                    date_str = tds[2].text.strip()
                    try:
                        # Apache format: 2021-08-30 11:23
                        last_modified = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                    except ValueError:
                        pass
            
            yield {
                'url': file_url,
                'filename': decoded_filename,
                'last_modified_hint': last_modified
            }

    @staticmethod
    def get_file_metadata(file_url: str):
        """
        Performs a HEAD request to fetch the Last-Modified header.
        """
        try:
            head_resp = requests.head(file_url, timeout=10)
            head_resp.raise_for_status()
            
            last_modified_str = head_resp.headers.get('Last-Modified')
            last_modified = None
            if last_modified_str:
                last_modified = parsedate_to_datetime(last_modified_str)
                # Convert to naive UTC datetime if timezone aware
                if last_modified.tzinfo is not None:
                    last_modified = last_modified.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                
            return {
                'last_modified': last_modified,
                'content_length': head_resp.headers.get('Content-Length')
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"HEAD request failed for {file_url}: {e}")
            return None
