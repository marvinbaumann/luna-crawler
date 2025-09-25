from flask import Flask, request, render_template_string, send_file, url_for, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
import csv
import io
import os
import threading
import time
from datetime import datetime

app = Flask(__name__)
app.static_folder = 'static'

crawl_sessions = {}
LOG_FILE = "crawl_log.txt"
EXCLUDED_EXTENSIONS = [
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.rar', '.7z', '.mp4', '.mp3'
]


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def normalize_url(url, keep_query=True):
    parsed = urlparse(url)
    if keep_query:
        parsed = parsed._replace(fragment="")
    else:
        parsed = parsed._replace(query="", fragment="")
    return parsed.geturl()


def is_valid_html_response(response):
    content_type = response.headers.get('Content-Type', '')
    return response.status_code == 200 and 'text/html' in content_type.lower()


def is_excluded(url):
    return any(url.lower().endswith(ext) for ext in EXCLUDED_EXTENSIONS)


def crawl_website(session_id, start_url):
    visited = set()
    queue = [start_url]
    base_domain = urlparse(start_url).netloc
    found_paths = []

    crawl_sessions[session_id] = {
        "status": "running",
        "current": "",
        "found": 0,
        "results": []
    }

    log(f"Crawl gestartet für Domain: {start_url}")

    while queue:
        url = queue.pop(0)
        clean_url = normalize_url(url, keep_query=True)
        if clean_url in visited or is_excluded(clean_url):
            continue
        try:
            crawl_sessions[session_id]["current"] = clean_url
            response = requests.get(url, timeout=5)
            if is_valid_html_response(response):
                visited.add(clean_url)
                found_paths.append(clean_url)
                crawl_sessions[session_id]["found"] = len(found_paths)
                soup = BeautifulSoup(response.text, 'html.parser')
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    full_url = urljoin(url, href)
                    full_url = normalize_url(full_url, keep_query=True)
                    parsed_url = urlparse(full_url)
                    if parsed_url.netloc == base_domain and full_url not in visited and full_url not in queue and not is_excluded(full_url):
                        queue.append(full_url)
        except:
            continue

    crawl_sessions[session_id]["status"] = "done"
    crawl_sessions[session_id]["results"] = sorted(set(found_paths))

    log(f"Crawl beendet für {start_url} – Gefundene Seiten: {len(found_paths)}")
    for p in crawl_sessions[session_id]["results"]:
        log(f"  - {p}")


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <title>Luna Website Crawler</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        img.logo { max-width: 200px; margin-bottom: 20px; }
        form, h1, h2, h3, p, ul { max-width: 800px; }
        details summary { cursor: pointer; font-weight: bold; margin-bottom: 10px; }
        details ul { margin-left: 20px; }
    </style>
    <script>
        let sessionId = Math.random().toString(36).substring(2);

        document.addEventListener("DOMContentLoaded", function() {
            const form = document.getElementById("crawlForm");
            form.addEventListener("submit", function(e) {
                e.preventDefault();
                const domain = document.getElementById('domain').value;
                document.getElementById('status').innerText = 'Starte Crawl...';
                fetch('/start_crawl', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ domain: domain, session: sessionId })
                });
                pollStatus();
            });
        });

        function pollStatus() {
            fetch(`/status?session=${sessionId}`).then(r => r.json()).then(data => {
                if (data.status === 'done') {
                    window.location.href = `/?session=${sessionId}`;
                } else {
                    document.getElementById('status').innerText =
                        `Status: ${data.status} | Gefunden: ${data.found} | Aktuell: ${data.current}`;
                    setTimeout(pollStatus, 1000);
                }
            });
        }
    </script>
</head>
<body>
    <img src=\"{{ url_for('static', filename='horizontal_logo_black.png') }}\" alt=\"Luna Logo\" class=\"logo\">
    <h1>Luna Webcrawler & Angebotsrechner</h1>
    <form id=\"crawlForm\">
        <label for=\"domain\">Domain eingeben (inkl. https://):</label>
        <input type=\"text\" name=\"domain\" id=\"domain\" required>
        <button type=\"submit\">Crawlen</button>
    </form>
    <p id=\"status\"></p>
    {% if results %}
        <h2>Gefundene Unterseiten ({{ results|length }})</h2>
        <details>
            <summary>Unterseiten anzeigen/verstecken</summary>
            <ul>
            {% for url in results %}
                <li><a href=\"{{ url }}\" target=\"_blank\">{{ url }}</a></li>
            {% endfor %}
            </ul>
        </details>

        <h3>Berechnetes Luna-Paket:</h3>
        <p><strong>{{ package }}</strong></p>
        <p><strong>Preis: {{ price }}</strong></p>
        <p><strong>Monatliche Gebühr: {{ monthly }}</strong></p>

        <form method=\"POST\" action=\"/download\">
            <input type=\"hidden\" name=\"urls\" value=\"{{ results|join(',') }}\">
            <button type=\"submit\">CSV herunterladen</button>
        </form>
    {% endif %}
</body>
</html>
"""

def calculate_package(num_pages):
    if num_pages <= 50:
        return "Starter", "12.000 €", "697 €/Monat"
    elif num_pages <= 100:
        return "Professional", "15.000 €", "997 €/Monat"
    elif num_pages <= 200:
        return "Advanced", "18.000 €", "1.497 €/Monat"
    else:
        extra_blocks = (num_pages - 1) // 200
        price = 18000 + (extra_blocks * 1000)
        return "Enterprise", f"{price:,} €".replace(",", "."), "1.997 €/Monat"

@app.route('/')
def index():
    session = request.args.get("session")
    data = crawl_sessions.get(session)
    if data and data["status"] == "done":
        urls = data["results"]
        package, price, monthly = calculate_package(len(urls))
        return render_template_string(HTML_TEMPLATE, results=urls, package=package, price=price, monthly=monthly)
    return render_template_string(HTML_TEMPLATE, results=None, package=None, price=None, monthly=None)

@app.route('/start_crawl', methods=['POST'])
def start_crawl():
    import json
    data = request.get_json()
    domain = data.get("domain")
    session = data.get("session")
    thread = threading.Thread(target=crawl_website, args=(session, domain))
    thread.start()
    return '', 204

@app.route('/status')
def status():
    session = request.args.get("session")
    progress = crawl_sessions.get(session, {})
    return jsonify({
        "status": progress.get("status", "idle"),
        "current": progress.get("current", ""),
        "found": progress.get("found", 0)
    })

@app.route('/download', methods=['POST'])
def download():
    urls = request.form['urls'].split(',')
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Gefundene Unterseiten'])
    for url in urls:
        writer.writerow([url])
    output.seek(0)
    return send_file(io.BytesIO(output.read().encode('utf-8')), mimetype='text/csv', as_attachment=True, download_name='unterseiten_luna.csv')

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=10000)
