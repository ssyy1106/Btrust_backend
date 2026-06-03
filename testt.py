import requests
from bs4 import BeautifulSoup
import urllib3
from collections import defaultdict


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url1 = "https://docs.google.com/document/d/e/2PACX-1vTMOmshQe8YvaRXi6gEPKKlsC6UpFJSMAk4mQjLm_u1gmHdVVTaeh7nBNFBRlui0sTZ-snGwZM4DBCT/pub"
url = "https://docs.google.com/document/d/e/2PACX-1vSvM5gDlNvt7npYHhp_XfsJvuntUhq184By5xO_pA4b_gCWeXb6dM6ZxwN8rE6S4ghUsCj2VKR21oEP/pub"

def main(url: str):
    html = requests.get(url, verify=False).text

    soup = BeautifulSoup(html, "html.parser")

    # 找所有表格
    tables = soup.find_all("table")

    dic = defaultdict(lambda : ' ')
    results = []

    for table in tables:
        rows = table.find_all("tr")

        for row in rows[1:]:
            cols = row.find_all(["td", "th"])

            if len(cols) >= 3:
                try:
                    x = int(cols[0].get_text(strip=True))
                    char = cols[1].get_text(strip=True)
                    y = int(cols[2].get_text(strip=True))
                    dic[(x, y)] = char

                    results.append({
                        "x": x,
                        "y": y,
                        "char": char
                    })
                except:
                    pass
    cols, rows = max(item["x"] for item in results), max(item["y"] for item in results)
    for j in range(rows, -1, -1):
        for i in range(cols + 1):
            print(dic[(i, j)], end="")
        print()

if __name__ == "__main__":
    main(url)