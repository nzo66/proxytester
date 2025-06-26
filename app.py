import subprocess
import json
import uuid
import threading
import os
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, Response, render_template_string, session, jsonify
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

# Carica variabili d'ambiente
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallback-secret-key-change-this')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# Pool di thread per gestire test simultanei
executor = ThreadPoolExecutor(max_workers=10)

# Dizionario thread-safe per tracciare i test attivi
active_tests = {}
active_tests_lock = threading.Lock()

# Decorator per autenticazione
def require_auth(f):
    """Decorator per richiedere autenticazione HTTP Basic"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth = request.authorization
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        
        if not auth or auth.username != 'admin' or auth.password != admin_password:
            return jsonify({
                'error': 'Autenticazione richiesta',
                'message': 'Usa username: admin e la password configurata'
            }), 401, {'WWW-Authenticate': 'Basic realm="Admin Area"'}
        
        return f(*args, **kwargs)
    return decorated_function

# --- HTML Template ---
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
        .session-info { background: #e3f2fd; padding: 10px; border-radius: 5px; margin-bottom: 20px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌐 Web Proxy Tester</h1>
        <div class="session-info">
            <strong>ID Sessione:</strong> <span id="session-id">{{ session_id }}</span> | 
            <strong>Avviato:</strong> <span id="session-time">{{ session_time }}</span>
        </div>
        <p>Incolla la tua lista di proxy (uno per riga) nel box sottostante e avvia il test.</p>
        <textarea id="proxy-list" placeholder="1.2.3.4:8080\nsocks5://user:pass@5.6.7.8:1080\n..."></textarea>
        <button id="start-test-btn" class="btn" onclick="startTest()">Avvia Test</button>
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
        const sessionId = '{{ session_id }}';

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

            if (abortController) abortController.abort();
            abortController = new AbortController();

            fetch('/test', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Session-ID': sessionId
                },
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
                            statusBar.innerText = `Test completato: ${testedCount} / ${proxies.length}`;
                            return;
                        }
                        buffer += new TextDecoder().decode(value, {stream:true});
                        let parts = buffer.split('\\n\\n');
                        buffer = parts.pop();
                        for (let part of parts) {
                            if (part.startsWith('data: ')) {
                                const data = JSON.parse(part.slice(6));
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
            }).catch(error => {
                if (error.name !== 'AbortError') {
                    console.error('Errore durante il test:', error);
                    statusBar.innerText = 'Errore durante il test';
                }
                testButton.disabled = false;
                testButton.innerText = 'Avvia Test';
                document.getElementById('stop-test-btn').disabled = true;
            });
        }

        function stopTest() {
            if (abortController) abortController.abort();
            
            // Invia richiesta di stop al server
            fetch('/stop', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Session-ID': sessionId
                },
                body: JSON.stringify({session_id: sessionId})
            });

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
            a.download = `proxy_funzionanti_${sessionId.substring(0,8)}.txt`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        window.addEventListener('beforeunload', () => {
            if (abortController) abortController.abort();
        });
    </script>
</body>
</html>
"""

# --- Backend Logic ---
URL_TO_TEST = 'https://new.newkso.ru/wind/'

def test_single_proxy(proxy_line, proxy_type, address_for_curl, session_id):
    """Test thread-safe per singolo proxy"""
    try:
        # Controlla se il test è stato fermato
        with active_tests_lock:
            if session_id not in active_tests or not active_tests[session_id]['running']:
                return {'status': 'STOPPED', 'details': 'Test fermato dall\'utente', 'is_protocol_error': False}

        # Primo test: sito principale
        cmd = ['curl', '-k', '--max-time', '10', '--silent', '--show-error', '--connect-timeout', '7', URL_TO_TEST]
        if proxy_type == 'socks5':
            cmd.extend(['--socks5-hostname', address_for_curl])
        elif proxy_type == 'http':
            cmd.extend(['--proxy', address_for_curl])
        else:
            return {'status': 'FAIL', 'details': f'Tipo di proxy non supportato: {proxy_type}', 'is_protocol_error': False}

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        # Controlla di nuovo se fermato dopo il primo comando
        with active_tests_lock:
            if session_id not in active_tests or not active_tests[session_id]['running']:
                return {'status': 'STOPPED', 'details': 'Test fermato dall\'utente', 'is_protocol_error': False}
        
        if result.returncode != 0:
            error_msg = result.stderr.strip().lower()
            protocol_error_keywords = ["unsupported proxy scheme", "malformed", "proxy connect command failed", 
                                     "received http/0.9 when not allowed", "proxy handshake", "ssl connect error", 
                                     "connect tunnel failed"]
            if any(keyword in error_msg for keyword in protocol_error_keywords):
                return {'status': 'FAIL', 'details': f'Protocollo {proxy_type} errato o handshake fallito', 'is_protocol_error': True}
            if "timed out" in error_msg: 
                return {'status': 'FAIL', 'details': 'Timeout (10s)', 'is_protocol_error': False}
            details = result.stderr.strip() or f'curl exit code {result.returncode}'
            return {'status': 'FAIL', 'details': details, 'is_protocol_error': False}
        else:
            output_lower = result.stdout.lower()
            if '404' in output_lower or 'error' in output_lower:
                return {'status': 'FAIL', 'details': 'Risposta HTTP 404 o errore nel contenuto', 'is_protocol_error': False}
        
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
        
        # Controlla se fermato dopo il secondo comando
        with active_tests_lock:
            if session_id not in active_tests or not active_tests[session_id]['running']:
                return {'status': 'STOPPED', 'details': 'Test fermato dall\'utente', 'is_protocol_error': False}
        
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
    # Crea una sessione unica per ogni utente
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        session['session_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template_string(HTML_TEMPLATE, 
                                session_id=session['session_id'],
                                session_time=session['session_time'])

@app.route('/test', methods=['POST'])
def test_proxies_stream():
    session_id = request.headers.get('X-Session-ID') or session.get('session_id', str(uuid.uuid4()))
    proxy_list_str = request.form.get('proxies', '')
    proxies = [line.strip() for line in proxy_list_str.split('\n') if line.strip()]

    # Registra il test attivo
    with active_tests_lock:
        active_tests[session_id] = {
            'running': True,
            'start_time': datetime.now(),
            'total_proxies': len(proxies)
        }

    def generate_results():
        try:
            for line in proxies:
                # Controlla se il test è stato fermato
                with active_tests_lock:
                    if session_id not in active_tests or not active_tests[session_id]['running']:
                        break

                result = None
                
                # Test del proxy con gestione protocolli
                if line.startswith(('socks5h://', 'socks5://')):
                    proxy_address = line.split('//', 1)[1]
                    result = test_single_proxy(line, 'socks5', proxy_address, session_id)
                elif line.startswith(('http://', 'https://')):
                    result = test_single_proxy(line, 'http', line, session_id)
                else:
                    # Prova prima come HTTP
                    result_http = test_single_proxy(line, 'http', line, session_id)
                    if result_http['status'] == 'SUCCESS':
                        result = result_http
                    elif result_http['status'] == 'STOPPED':
                        result = result_http
                    else:
                        # Se fallisce, prova come SOCKS5
                        result_socks = test_single_proxy(line, 'socks5', line, session_id)
                        if result_socks['status'] == 'SUCCESS':
                            result = result_socks
                        elif result_socks['status'] == 'STOPPED':
                            result = result_socks
                        else:
                            result = result_http

                # Se il test è stato fermato, interrompi
                if result['status'] == 'STOPPED':
                    break

                data_to_send = result.copy()
                data_to_send['proxy'] = line
                
                if result['status'] == 'SUCCESS':
                    protocol_used = result.get('protocol_used', 'sconosciuto')
                    proxy_to_save = line
                    if protocol_used == 'http' and not line.startswith(('http://', 'https://')):
                        proxy_to_save = f"http://{line}"
                    elif protocol_used == 'socks5' and not line.startswith(('socks5://', 'socks5h://')):
                        proxy_to_save = f"socks5://{line}"
                    data_to_send['proxy_to_save'] = proxy_to_save

                print(f"[{session_id[:8]}] Risultato per {line}: {data_to_send}")
                yield f"data: {json.dumps(data_to_send)}\n\n"
        
        finally:
            # Pulisci il test attivo
            with active_tests_lock:
                if session_id in active_tests:
                    del active_tests[session_id]
    
    return Response(generate_results(), mimetype='text/event-stream')

@app.route('/stop', methods=['POST'])
def stop_test():
    """Endpoint per fermare un test in corso"""
    data = request.get_json()
    session_id = data.get('session_id') if data else None
    
    if not session_id:
        session_id = request.headers.get('X-Session-ID') or session.get('session_id')
    
    if session_id:
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]['running'] = False
                print(f"[{session_id[:8]}] Test fermato dall'utente")
    
    return {'status': 'stopped'}

@app.route('/status')
@require_auth
def get_status():
    """Endpoint protetto per ottenere lo stato dei test attivi"""
    with active_tests_lock:
        active_count = len(active_tests)
        tests_info = []
        for sid, info in active_tests.items():
            tests_info.append({
                'session_id': sid[:8],
                'full_session_id': sid,
                'running': info['running'],
                'start_time': info['start_time'].strftime('%H:%M:%S'),
                'start_date': info['start_time'].strftime('%Y-%m-%d'),
                'total_proxies': info['total_proxies']
            })
    
    return {
        'active_tests': active_count,
        'tests': tests_info,
        'server_info': {
            'version': '2.0',
            'multi_user': True,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    }

@app.route('/admin')
@require_auth
def admin_panel():
    """Pannello admin protetto"""
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Panel - Proxy Tester</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #2c5aa0; }
            .status-box { background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 10px 0; }
            .session-box { background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 5px 0; border-left: 4px solid #28a745; }
            .session-box.stopped { border-left-color: #dc3545; }
            button { padding: 10px 20px; background: #2c5aa0; color: white; border: none; border-radius: 5px; cursor: pointer; margin: 5px; }
            button:hover { background: #1e3d6f; }
            .refresh-btn { background: #28a745; }
            .json-btn { background: #17a2b8; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #f2f2f2; }
            .running { color: #28a745; font-weight: bold; }
            .stopped { color: #dc3545; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔧 Admin Panel - Proxy Tester</h1>
            <div class="status-box">
                <h3>Stato Server</h3>
                <p><strong>Versione:</strong> 2.0 Multi-User</p>
                <p><strong>Sessioni Attive:</strong> <span id="active-count">-</span></p>
                <p><strong>Ultimo Aggiornamento:</strong> <span id="last-update">-</span></p>
            </div>
            
            <button class="refresh-btn" onclick="loadStatus()">🔄 Aggiorna Stato</button>
            <button class="json-btn" onclick="window.open('/status', '_blank')">📊 Vedi JSON Status</button>
            <button onclick="window.open('/', '_blank')">🏠 Vai all'App</button>
            
            <div id="sessions-container">
                <h3>Sessioni Attive</h3>
                <div id="sessions-list"></div>
                <table id="sessions-table" style="display:none;">
                    <thead>
                        <tr>
                            <th>ID Sessione</th>
                            <th>Stato</th>
                            <th>Avviato</th>
                            <th>Data</th>
                            <th>Proxy Totali</th>
                        </tr>
                    </thead>
                    <tbody id="sessions-tbody">
                    </tbody>
                </table>
            </div>
        </div>
        
        <script>
            function loadStatus() {
                fetch('/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('active-count').textContent = data.active_tests;
                    document.getElementById('last-update').textContent = new Date().toLocaleString();
                    
                    const sessionsList = document.getElementById('sessions-list');
                    const sessionsTable = document.getElementById('sessions-table');
                    const sessionsTableBody = document.getElementById('sessions-tbody');
                    
                    if (data.tests.length > 0) {
                        // Mostra tabella
                        sessionsList.style.display = 'none';
                        sessionsTable.style.display = 'table';
                        
                        // Pulisci tabella
                        sessionsTableBody.innerHTML = '';
                        
                        // Popola tabella
                        data.tests.forEach(test => {
                            const row = document.createElement('tr');
                            const statusClass = test.running ? 'running' : 'stopped';
                            const statusText = test.running ? '🟢 Attivo' : '🔴 Fermato';
                            
                            row.innerHTML = `
                                <td><code>${test.session_id}</code></td>
                                <td><span class="${statusClass}">${statusText}</span></td>
                                <td>${test.start_time}</td>
                                <td>${test.start_date}</td>
                                <td>${test.total_proxies}</td>
                            `;
                            sessionsTableBody.appendChild(row);
                        });
                    } else {
                        // Mostra messaggio
                        sessionsTable.style.display = 'none';
                        sessionsList.style.display = 'block';
                        sessionsList.innerHTML = '<p>🎉 Nessuna sessione attiva</p>';
                    }
                })
                .catch(error => {
                    console.error('Errore:', error);
                    alert('Errore nel caricamento dello stato. Verifica le credenziali.');
                });
            }
            
            // Carica stato iniziale
            loadStatus();
            
            // Auto-refresh ogni 30 secondi
            setInterval(loadStatus, 30000);
        </script>
    </body>
    </html>
    """)

if __name__ == '__main__':
    print("Avvio del server Proxy Tester Web Multi-Utente...")
    print("Apri http://127.0.0.1:7860 nel tuo browser.")
    print("Admin panel: http://127.0.0.1:7860/admin")
    print("Status API: http://127.0.0.1:7860/status")
    print(f"Admin password: {os.getenv('ADMIN_PASSWORD', 'admin123')}")
    app.run(host='0.0.0.0', port=7860, debug=False, threaded=True)
