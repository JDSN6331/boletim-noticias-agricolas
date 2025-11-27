import requests
from bs4 import BeautifulSoup as BS
url='https://www.noticiasagricolas.com.br/defesa-do-produtor-rural/'
headers={'User-Agent':'Mozilla/5.0'}
resp=requests.get(url,headers=headers,timeout=10)
soup=BS(resp.text,'lxml')
for li in soup.select('li.horizontal')[:5]:
    title=li.find('h2')
    print(title.get_text(strip=True) if title else 'no title')
