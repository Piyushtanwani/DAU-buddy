import requests
from bs4 import BeautifulSoup

def scrape_scholars() -> list[dict]:
    url = "https://www.daiict.ac.in/doctoral-scholars"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }
    print(f"Fetching data from {url}...")
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch page. Status code: {response.status_code}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    blocks = soup.find_all('div', class_='doctoralScholarsBlock')
    
    scholars = []
    
    for block in blocks:
        scholar = {
            'name': None,
            'image_url': None,
            'year_of_joining': None,
            'year_of_graduation': None,
            'advisor': None,
            'thesis_topic': None,
            'areas_of_research': None,
            'publications': None,
            'awards': None,
            'post_phd_employment': None,
            'personal_webpage': None
        }
        
        name_div = block.find('span', class_='docName')
        if name_div:
            scholar['name'] = name_div.get_text(strip=True)
            
        img_div = block.find('div', class_='scholarsPhoto')
        if img_div:
            img = img_div.find('img')
            if img and img.get('src'):
                src = img.get('src')
                scholar['image_url'] = "https://www.daiict.ac.in" + src if src.startswith('/') else src

        sub_infos = block.find_all('div', class_='subInfoBlock')
        for info in sub_infos:
            title_elem = info.find('span', class_='subTitle')
            val_elem = info.find('span', class_='subInformation')
            
            if title_elem and val_elem:
                title = title_elem.get_text(strip=True).replace(':', '').strip().lower()
                val = val_elem.get_text(strip=True)
                
                if 'year of joining' in title:
                    scholar['year_of_joining'] = val
                elif 'year of graduation' in title:
                    scholar['year_of_graduation'] = val
                elif 'advisor' in title:
                    scholar['advisor'] = val
                elif 'thesis topic' in title:
                    scholar['thesis_topic'] = val
                elif 'areas of research' in title:
                    scholar['areas_of_research'] = val
                elif 'journals/conferences' in title:
                    scholar['publications'] = val
                elif 'awards' in title or 'honors' in title:
                    scholar['awards'] = val
                elif 'post phd employment' in title:
                    scholar['post_phd_employment'] = val
                elif 'personal webpage' in title:
                    scholar['personal_webpage'] = val

        if scholar['name']:
            scholars.append(scholar)

    print(f"Found {len(scholars)} scholars.")
    return scholars

if __name__ == "__main__":
    data = scrape_scholars()
    print(f"Scraped {len(data)} items successfully.")
