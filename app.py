import subprocess
import json
from flask import Flask, request, Response, render_template_string

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB, puoi aumentare se serve

# --- HTML, CSS, JS for the Web Interface ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Proxy Tester Web</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; background-color: #f5f5f5; color: #333; }
        .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #2c5aa0; text-align: center; margin-bottom: 20px; }
        textarea { width: 100%; height: 200px; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; font-family: 'Courier New', monospace; }
        .btn { display: inline-block; padding: 12px 25px; background: #2c5aa0; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; cursor: pointer; border: none; font-size: 16px; width: 100%; }
        .btn:hover { background: #1e3d6f; }
        .btn:disabled { background: #ccc; cursor: not-allowed; }
        .results-container { display: flex; gap: 20px; margin-top: 30px; }
        .result-box { flex: 1; background: #f8f9fa; padding: 20px; border-radius: 5px; border-left: 4px solid; }
        .result-box h2 { margin-top: 0; font-size: 18px; border-bottom: 1px solid #ddd; padding-bottom: 10px; }
        #working-proxies { border-left-color: #28a745; }
        #failed-proxies { border-left-color: #dc3545; }
        .result-box ul { list-style-type: none; padding: 0; margin: 0; max-height: 400px; overflow-y: auto; }
        .result-box li { padding: 8px; border-bottom: 1px solid #eee; font-family: 'Courier New', monospace; font-size: 14px; word-break: break-all; }
        .result-box li:last-child { border-bottom: none; }
        .status-bar { margin-top: 20px; text-align: center; font-weight: bold; }
        .success { color: #28a745; }
        .failure { color: #dc3545; }
        .protocol { font-size: 0.8em; color: #666; background-color: #e9ecef; padding: 2px 5px; border-radius: 3px; margin-left: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌐 Web Proxy Tester</h1>
        <p>Incolla la tua lista di proxy (uno per riga) nel box sottostante e avvia il test.</p>
        <textarea id="proxy-list" placeholder="1.2.3.4:8080\nsocks5://user:pass@5.6.7.8:1080\n..."></textarea>
        <button id="start-test-btn" class="btn" onclick="startTest()">Avvia Test</button>
        <!-- Sotto il bottone Avvia Test -->
        <button id="download-btn" class="btn" style="background:#28a745;margin-top:10px;" onclick="downloadWorkingProxies()" disabled>Scarica Proxy Funzionanti</button>
        <button id="stop-test-btn" class="btn" style="background:#dc3545;margin-top:10px;" onclick="stopTest()" disabled>Stop Test</button>
        
        <div id="status-bar" class="status-bar"></div>

        <div class="results-container">
            <div id="working-proxies" class="result-box">
                <h2>✅ Funzionanti (<span id="working-count">0</span>)</h2>
                <ul id="working-list"></ul>
            </div>
            <div id="failed-proxies" class="result-box">
                <h2>❌ Non Funzionanti (<span id="failed-count">0</span>)</h2>
                <ul id="failed-list"></ul>
            </div>
        </div>
    </div>

    <script>
        let abortController = null;

        function startTest() {
            const proxyList = document.getElementById('proxy-list').value;
            const proxies = proxyList.split('\\n').map(p => p.trim()).filter(p => p);
            
            if (proxies.length === 0) {
                alert('Per favore, inserisci almeno un proxy.');
                return;
            }

            // Reset UI
            document.getElementById('working-list').innerHTML = '';
            document.getElementById('failed-list').innerHTML = '';
            document.getElementById('working-count').innerText = '0';
            document.getElementById('failed-count').innerText = '0';
            const statusBar = document.getElementById('status-bar');
            const testButton = document.getElementById('start-test-btn');
            testButton.disabled = true;
            testButton.innerText = 'Test in corso...';
            document.getElementById('stop-test-btn').disabled = false;
            
            let testedCount = 0;
            let workingCount = 0;
            let failedCount = 0;

            statusBar.innerText = `Test in corso... 0 / ${proxies.length}`;

            // Annulla eventuale test precedente
            if (abortController) abortController.abort();
            abortController = new AbortController();

            fetch('/test', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'proxies=' + encodeURIComponent(proxyList),
                signal: abortController.signal
            }).then(response => {
                const reader = response.body.getReader();
                let buffer = '';
                function read() {
                    reader.read().then(({done, value}) => {
                        if (done) {
                            testButton.disabled = false;
                            testButton.innerText = 'Avvia Test';
                            document.getElementById('stop-test-btn').disabled = true;
                            return;
                        }
                        buffer += new TextDecoder().decode(value, {stream:true});
                        let parts = buffer.split('\\n\\n');
                        buffer = parts.pop();
                        for (let part of parts) {
                            if (part.startsWith('data: ')) {
                                const data = JSON.parse(part.slice(6));
                                // ...gestione come prima...
                                testedCount++;
                                statusBar.innerText = `Test in corso... ${testedCount} / ${proxies.length}`;
                                if (data.status === 'SUCCESS') {
                                    workingCount++;
                                    const list = document.getElementById('working-list');
                                    const item = document.createElement('li');
                                    item.innerHTML = `<span class="success">${data.proxy_to_save}</span> <span class="protocol">${data.protocol_used}</span>`;
                                    list.appendChild(item);
                                    document.getElementById('working-count').innerText = workingCount;
                                    document.getElementById('download-btn').disabled = false;
                                } else {
                                    failedCount++;
                                    const list = document.getElementById('failed-list');
                                    const item = document.createElement('li');
                                    item.innerHTML = `<span class="failure">${data.proxy}</span> - ${data.details}`;
                                    list.appendChild(item);
                                    document.getElementById('failed-count').innerText = failedCount;
                                }
                            }
                        }
                        read();
                    });
                }
                read();
            });
        }

        function stopTest() {
            if (abortController) abortController.abort();
            document.getElementById('start-test-btn').disabled = false;
            document.getElementById('start-test-btn').innerText = 'Avvia Test';
            document.getElementById('stop-test-btn').disabled = true;
            document.getElementById('status-bar').innerText = 'Test interrotto.';
        }

        function downloadWorkingProxies() {
            const items = document.querySelectorAll('#working-list li .success');
            const proxies = Array.from(items).map(span => span.textContent.trim()).join('\\n');
            const blob = new Blob([proxies], {type: 'text/plain'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'proxy_funzionanti.txt';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        // Annulla il test se la pagina viene ricaricata o chiusa
        window.addEventListener('beforeunload', () => {
            if (abortController) abortController.abort();
        });
    </script>
</body>
</html>
"""

# --- Backend Logic (adapted from test.py) ---
URL_TO_TEST = 'https://new.newkso.ru/wind/'

def test_single_proxy(proxy_line, proxy_type, address_for_curl):
    try:
        # Primo test: sito principale
        cmd = ['curl', '-k', '--max-time', '10', '--silent', '--show-error', '--connect-timeout', '7', URL_TO_TEST]
        if proxy_type == 'socks5':
            cmd.extend(['--socks5-hostname', address_for_curl])
        elif proxy_type == 'http':
            cmd.extend(['--proxy', address_for_curl])
        else:
            return {'status': 'FAIL', 'details': f'Tipo di proxy non supportato internamente: {proxy_type}', 'is_protocol_error': False}

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode != 0:
            error_msg = result.stderr.strip().lower()
            protocol_error_keywords = ["unsupported proxy scheme", "malformed", "proxy connect command failed", "received http/0.9 when not allowed", "proxy handshake", "ssl connect error", "connect tunnel failed"]
            if any(keyword in error_msg for keyword in protocol_error_keywords):
                return {'status': 'FAIL', 'details': f'Protocollo {proxy_type} errato o handshake fallito', 'is_protocol_error': True}
            if "timed out" in error_msg: return {'status': 'FAIL', 'details': 'Timeout (10s)', 'is_protocol_error': False}
            details = result.stderr.strip() or f'curl exit code {result.returncode}'
            return {'status': 'FAIL', 'details': details, 'is_protocol_error': False}
        else:
            output_lower = result.stdout.lower();
            if '404' in output_lower or 'error' in output_lower:
                return {'status': 'FAIL', 'details': 'Risposta HTTP 404 o errore nel contenuto', 'is_protocol_error': False, 'protocol_used': proxy_type}
        
        # Secondo test: vavoo.to
        VAVOO_URL = 'https://vavoo.to/play/1534161807/index.m3u8'
        cmd2 = [
            'curl', '-k', '--max-time', '10', '--silent', '--show-error', '--connect-timeout', '7',
            '-H', 'user-agent: VAVOO/2.6',
            '-H', 'referer: https://vavoo.to/',
            '-H', 'origin: https://vavoo.to',
            VAVOO_URL
        ]
        if proxy_type == 'socks5':
            cmd2.extend(['--socks5-hostname', address_for_curl])
        elif proxy_type == 'http':
            cmd2.extend(['--proxy', address_for_curl])
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=15)
        if result2.returncode != 0:
            return {'status': 'FAIL', 'details': 'Errore su vavoo.to', 'is_protocol_error': False}
        if result2.stdout.strip() == '{"error":"Not found"}':
            return {'status': 'FAIL', 'details': 'Risposta vavoo.to: Not found', 'is_protocol_error': False}
        
        return {'status': 'SUCCESS', 'details': 'Connessione riuscita', 'is_protocol_error': False, 'protocol_used': proxy_type}
    except subprocess.TimeoutExpired:
        return {'status': 'FAIL', 'details': 'Timeout script (15s)', 'is_protocol_error': False}
    except Exception as e:
        return {'status': 'FAIL', 'details': f'Errore esecuzione script: {e}', 'is_protocol_error': False}

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/test', methods=['POST'])
def test_proxies_stream():
    proxy_list_str = request.form.get('proxies', '')
    proxies = [line.strip() for line in proxy_list_str.split('\n') if line.strip()]

    def generate_results():
        for line in proxies:
            result = None
            # Se l'utente specifica il protocollo, usa quello
            if line.startswith(('socks5h://', 'socks5://')):
                proxy_address = line.split('//', 1)[1]
                result = test_single_proxy(line, 'socks5', proxy_address)
            elif line.startswith(('http://', 'https://')):
                result = test_single_proxy(line, 'http', line)
            else:
                # Prova prima come SOCKS5
                result_socks = test_single_proxy(line, 'socks5', line)
                if result_socks['status'] == 'SUCCESS':
                    result = result_socks
                else:
                    # Se fallisce, prova come HTTP
                    result_http = test_single_proxy(line, 'http', line)
                    if result_http['status'] == 'SUCCESS':
                        result = result_http
                    else:
                        # Se entrambi falliscono, mostra il risultato SOCKS5 (più informativo)
                        result = result_socks

            data_to_send = result.copy();
            data_to_send['proxy'] = line;
            if result['status'] == 'SUCCESS':
                protocol_used = result.get('protocol_used', 'sconosciuto');
                proxy_to_save = line;
                if protocol_used == 'http' and not line.startswith(('http://', 'https://')):
                    proxy_to_save = f"http://{line}";
                elif protocol_used == 'socks5' and not line.startswith(('socks5://', 'socks5h://')):
                    proxy_to_save = f"socks5://{line}";
                data_to_send['proxy_to_save'] = proxy_to_save;

            print("Risultato per", line, ":", data_to_send);
            yield f"data: {json.dumps(data_to_send)}\n\n";
    
    return Response(generate_results(), mimetype='text/event-stream')

if __name__ == '__main__':
    print("Avvio del server Proxy Tester Web...")
    print("Apri http://127.0.0.1:7860 nel tuo browser.")
    app.run(host='0.0.0.0', port=7860, debug=False)

