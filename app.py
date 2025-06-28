import subprocess
import json
import uuid
import threading
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, Response, render_template_string, session, jsonify
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
import time


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
    <title>Proxy Tester Web - Parallelo</title>
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
        .resume-notice { background: #fff3cd; border: 1px solid #ffeaa7; color: #856404; padding: 10px; border-radius: 5px; margin-bottom: 20px; }
        .parallel-info { background: #e8f5e8; border: 1px solid #4caf50; color: #2e7d32; padding: 10px; border-radius: 5px; margin-bottom: 20px; }
        .config-section { background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .config-section label { display: block; margin-bottom: 5px; font-weight: bold; }
        .config-section input[type="number"] { width: 80px; padding: 5px; border: 1px solid #ccc; border-radius: 3px; }
        .progress-bar { width: 100%; height: 20px; background-color: #e0e0e0; border-radius: 10px; overflow: hidden; margin: 10px 0; }
        .progress-fill { height: 100%; background-color: #4caf50; transition: width 0.3s ease; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Web Proxy Tester - Parallelo</h1>
        <div class="session-info">
            <strong>ID Sessione:</strong> <span id="session-id">{{ session_id }}</span> | 
            <strong>Avviato:</strong> <span id="session-time">{{ session_time }}</span>
        </div>
        <div class="parallel-info">
            ⚡ <strong>Modalità Parallela Attiva:</strong> I proxy vengono testati contemporaneamente per maggiore velocità!
        </div>
        <div id="resume-notice" class="resume-notice" style="display:none;">
            ⚠️ Test ripreso dopo ricaricamento pagina. I risultati precedenti potrebbero non essere visibili.
        </div>
        
        <div class="config-section">
            <label for="max-workers">Numero massimo di test paralleli:</label>
            <input type="number" id="max-workers" value="20" min="1" max="50">
            <small style="color: #666; margin-left: 10px;">Raccomandato: 10-30 (più alto = più veloce ma usa più risorse)</small>
        </div>
        
        <p>Incolla la tua lista di proxy (uno per riga) nel box sottostante e avvia il test parallelo.</p>
        <textarea id="proxy-list" placeholder="1.2.3.4:8080\nsocks5://user:pass@5.6.7.8:1080\n..."></textarea>
        <button id="start-test-btn" class="btn" onclick="startTest()">🚀 Avvia Test Parallelo</button>
        <button id="download-btn" class="btn" style="background:#28a745;margin-top:10px;" onclick="downloadWorkingProxies()" disabled>📥 Scarica Proxy Funzionanti</button>
        <button id="stop-test-btn" class="btn" style="background:#dc3545;margin-top:10px;" onclick="stopTest()" disabled>⏹️ Stop Test</button>
        
        <div id="status-bar" class="status-bar"></div>
        <div class="progress-bar">
            <div id="progress-fill" class="progress-fill" style="width: 0%;"></div>
        </div>

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
        let isPageUnloading = false;
        let heartbeatInterval = null;
        let isTestResumed = false;

        // Heartbeat per verificare la connessione
        function startHeartbeat() {
            heartbeatInterval = setInterval(function() {
                if (document.getElementById('start-test-btn').disabled && !isPageUnloading) {
                    fetch('/heartbeat', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Session-ID': sessionId
                        },
                        body: JSON.stringify({session_id: sessionId})
                    }).catch(function(error) {
                        console.log('Heartbeat failed:', error);
                    });
                }
            }, 30000); // Ogni 30 secondi
        }

        // Ferma il heartbeat
        function stopHeartbeat() {
            if (heartbeatInterval) {
                clearInterval(heartbeatInterval);
                heartbeatInterval = null;
            }
        }

        function updateProgress(completed, total) {
            const percentage = total > 0 ? (completed / total) * 100 : 0;
            document.getElementById('progress-fill').style.width = percentage + '%';
        }

        function startTest() {
            console.log('Avvio test parallelo...');
            
            const proxyList = document.getElementById('proxy-list').value;
            const proxies = proxyList.split('\\n').map(function(p) { return p.trim(); }).filter(function(p) { return p; });
            const maxWorkers = parseInt(document.getElementById('max-workers').value) || 20;
            
            console.log('Proxy trovati:', proxies.length);
            console.log('Max workers:', maxWorkers);
            
            if (proxies.length === 0) {
                alert('Per favore, inserisci almeno un proxy.');
                return;
            }

            // Salva lo stato nel localStorage
            localStorage.setItem('activeTest', JSON.stringify({
                sessionId: sessionId,
                proxies: proxies,
                maxWorkers: maxWorkers,
                startTime: Date.now()
            }));

            // Reset UI
            document.getElementById('working-list').innerHTML = '';
            document.getElementById('failed-list').innerHTML = '';
            document.getElementById('working-count').innerText = '0';
            document.getElementById('failed-count').innerText = '0';
            updateProgress(0, proxies.length);
            
            const statusBar = document.getElementById('status-bar');
            const testButton = document.getElementById('start-test-btn');
            testButton.disabled = true;
            testButton.innerText = '🚀 Test Parallelo in Corso...';
            document.getElementById('stop-test-btn').disabled = false;
            document.getElementById('max-workers').disabled = true;
            
            // Avvia heartbeat
            startHeartbeat();
            
            let completedCount = 0;
            let workingCount = 0;
            let failedCount = 0;

            statusBar.innerText = 'Test parallelo avviato con ' + maxWorkers + ' thread... 0 / ' + proxies.length + ' completati';

            if (abortController) abortController.abort();
            abortController = new AbortController();

            // Crea FormData correttamente
            const formData = new FormData();
            formData.append('proxies', proxyList);
            formData.append('max_workers', maxWorkers.toString());

            console.log('Invio richiesta al server...');

            fetch('/test', {
                method: 'POST',
                headers: {
                    'X-Session-ID': sessionId
                },
                body: formData,
                signal: abortController.signal
            }).then(function(response) {
                console.log('Risposta ricevuta:', response.status);
                
                if (!response.ok) {
                    throw new Error('Errore HTTP: ' + response.status);
                }
                
                const reader = response.body.getReader();
                let buffer = '';
                
                function read() {
                    reader.read().then(function(result) {
                        const done = result.done;
                        const value = result.value;
                        
                        if (done) {
                            console.log('Stream completato');
                            testButton.disabled = false;
                            testButton.innerText = '🚀 Avvia Test Parallelo';
                            document.getElementById('stop-test-btn').disabled = true;
                            document.getElementById('max-workers').disabled = false;
                            statusBar.innerText = '✅ Test completato: ' + completedCount + ' / ' + proxies.length + ' (' + workingCount + ' funzionanti, ' + failedCount + ' falliti)';
                            updateProgress(proxies.length, proxies.length);
                            stopHeartbeat();
                            localStorage.removeItem('activeTest');
                            return;
                        }
                        
                        buffer += new TextDecoder().decode(value, {stream:true});
                        let parts = buffer.split('\\n\\n');
                        buffer = parts.pop();
                        
                        for (let i = 0; i < parts.length; i++) {
                            const part = parts[i];
                            if (part.startsWith('data: ')) {
                                try {
                                    const data = JSON.parse(part.slice(6));
                                    console.log('Risultato ricevuto:', data);
                                    
                                    completedCount++;
                                    updateProgress(completedCount, proxies.length);
                                    statusBar.innerText = '⚡ Test parallelo: ' + completedCount + ' / ' + proxies.length + ' completati (' + workingCount + ' ✅, ' + failedCount + ' ❌)';
                                    
                                    if (data.status === 'SUCCESS') {
                                        workingCount++;
                                        const list = document.getElementById('working-list');
                                        const item = document.createElement('li');
                                        // Mostra anche la velocità se presente
                                        let speedInfo = '';
                                        if (typeof data.speedtest_mbps !== 'undefined') {
                                            speedInfo = ` <span style="color:#007bff;font-size:0.9em;">${data.speedtest_mbps} Mbps</span>`;
                                        }
                                        item.innerHTML = '<span class="success">' + data.proxy_to_save + '</span> <span class="protocol">' + data.protocol_used + '</span>' + speedInfo;
                                        list.appendChild(item);
                                        document.getElementById('working-count').innerText = workingCount;
                                        document.getElementById('download-btn').disabled = false;
                                    } else if (data.status === 'FAIL') {
                                        failedCount++;
                                        const list = document.getElementById('failed-list');
                                        const item = document.createElement('li');
                                        item.innerHTML = '<span class="failure">' + data.proxy + '</span> - ' + data.details;
                                        list.appendChild(item);
                                        document.getElementById('failed-count').innerText = failedCount;
                                    }
                                } catch (e) {
                                    console.error('Errore parsing JSON:', e, 'Data:', part.slice(6));
                                }
                            }
                        }
                        read();
                    }).catch(function(error) {
                        console.error('Errore lettura stream:', error);
                        testButton.disabled = false;
                        testButton.innerText = '🚀 Avvia Test Parallelo';
                        document.getElementById('stop-test-btn').disabled = true;
                        document.getElementById('max-workers').disabled = false;
                        statusBar.innerText = '❌ Errore durante la lettura dei risultati';
                        stopHeartbeat();
                    });
                }
                read();
            }).catch(function(error) {
                console.error('Errore durante il test:', error);
                if (error.name !== 'AbortError') {
                    statusBar.innerText = '❌ Errore durante il test: ' + error.message;
                }
                testButton.disabled = false;
                testButton.innerText = '🚀 Avvia Test Parallelo';
                document.getElementById('stop-test-btn').disabled = true;
                document.getElementById('max-workers').disabled = false;
                stopHeartbeat();
                localStorage.removeItem('activeTest');
            });
        }

        function stopTest() {
            if (abortController) abortController.abort();
            
            // Ferma heartbeat
            stopHeartbeat();
            
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
            document.getElementById('start-test-btn').innerText = '🚀 Avvia Test Parallelo';
            document.getElementById('stop-test-btn').disabled = true;
            document.getElementById('max-workers').disabled = false;
            document.getElementById('status-bar').innerText = '⏹️ Test interrotto.';
            
            // Rimuovi lo stato dal localStorage
            localStorage.removeItem('activeTest');
        }

        function resumeTestMonitoring() {
            if (abortController) abortController.abort();
            abortController = new AbortController();
            
            // Avvia heartbeat per il test ripreso
            startHeartbeat();
            
            fetch('/test/resume', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Session-ID': sessionId
                },
                body: JSON.stringify({session_id: sessionId}),
                signal: abortController.signal
            }).then(function(response) {
                if (!response.ok) {
                    throw new Error('Sessione non trovata');
                }
                
                const reader = response.body.getReader();
                let buffer = '';
                function read() {
                    reader.read().then(function(result) {
                        if (result.done) {
                            document.getElementById('start-test-btn').disabled = false;
                            document.getElementById('start-test-btn').innerText = '🚀 Avvia Test Parallelo';
                            document.getElementById('stop-test-btn').disabled = true;
                            document.getElementById('max-workers').disabled = false;
                            document.getElementById('status-bar').innerText = '✅ Test completato';
                            stopHeartbeat();
                            localStorage.removeItem('activeTest');
                            return;
                        }
                        buffer += new TextDecoder().decode(result.value, {stream:true});
                        let parts = buffer.split('\\n\\n');
                        buffer = parts.pop();
                        for (let i = 0; i < parts.length; i++) {
                            const part = parts[i];
                            if (part.startsWith('data: ')) {
                                const data = JSON.parse(part.slice(6));
                                
                                if (data.status === 'RESUMED') {
                                    document.getElementById('status-bar').innerText = data.message;
                                    continue;
                                }
                                
                                if (data.status === 'SUCCESS') {
                                    const list = document.getElementById('working-list');
                                    const item = document.createElement('li');
                                    item.innerHTML = '<span class="success">' + data.proxy_to_save + '</span> <span class="protocol">' + data.protocol_used + '</span>';
                                    list.appendChild(item);
                                    const currentCount = parseInt(document.getElementById('working-count').innerText);
                                    document.getElementById('working-count').innerText = currentCount + 1;
                                    document.getElementById('download-btn').disabled = false;
                                } else if (data.status === 'FAIL') {
                                    const list = document.getElementById('failed-list');
                                    const item = document.createElement('li');
                                    item.innerHTML = '<span class="failure">' + data.proxy + '</span> - ' + data.details;
                                    list.appendChild(item);
                                    const currentCount = parseInt(document.getElementById('failed-count').innerText);
                                    document.getElementById('failed-count').innerText = currentCount + 1;
                                }
                            }
                        }
                        read();
                    });
                }
                read();
            }).catch(function(error) {
                console.error('Errore nel riprendere il test:', error);
                document.getElementById('start-test-btn').disabled = false;
                document.getElementById('start-test-btn').innerText = '🚀 Avvia Test Parallelo';
                document.getElementById('stop-test-btn').disabled = true;
                document.getElementById('max-workers').disabled = false;
                document.getElementById('status-bar').innerText = '❌ Errore nel riprendere il test';
                stopHeartbeat();
            });
        }

        function downloadWorkingProxies() {
            const items = document.querySelectorAll('#working-list li .success');
            const proxies = Array.from(items).map(function(span) { return span.textContent.trim(); }).join('\\n');
            const blob = new Blob([proxies], {type: 'text/plain'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'proxy_funzionanti_' + sessionId.substring(0,8) + '.txt';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        // Gestione migliorata degli eventi di chiusura
        window.addEventListener('beforeunload', function(event) {
            isPageUnloading = true;
            
            // Ferma il heartbeat
            stopHeartbeat();
            
            // Interrompi la connessione fetch
            if (abortController) {
                abortController.abort();
            }
            
            // Invia richiesta di stop al server
            if (document.getElementById('start-test-btn').disabled) {
                const data = JSON.stringify({
                    session_id: sessionId,
                    reason: 'browser_closing'
                });
                
                if (navigator.sendBeacon) {
                    navigator.sendBeacon('/stop', data);
                }
                
                // Solo per reload, non per chiusura completa
                if (performance.navigation && performance.navigation.type === performance.navigation.TYPE_RELOAD) {
                    event.preventDefault();
                    event.returnValue = 'Un test è in corso. Ricaricando la pagina potresti perdere alcuni risultati.';
                    return event.returnValue;
                }
            }
        });

        // Gestione visibilità pagina (quando si cambia tab o si minimizza)
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                console.log('Pagina nascosta');
            } else {
                console.log('Pagina visibile');
                // Ricontrolla lo stato quando la pagina torna visibile
                if (!isPageUnloading) {
                    checkSessionStatus();
                }
            }
        });

        function checkSessionStatus() {
            fetch('/status/check', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Session-ID': sessionId
                },
                body: JSON.stringify({session_id: sessionId})
            })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.test_running && !document.getElementById('start-test-btn').disabled) {
                    // Ripristina l'interfaccia per il test in corso
                    document.getElementById('start-test-btn').disabled = true;
                    document.getElementById('start-test-btn').innerText = '🚀 Test Parallelo in Corso...';
                    document.getElementById('stop-test-btn').disabled = false;
                    document.getElementById('max-workers').disabled = true;
                    document.getElementById('status-bar').innerText = '⚡ Test parallelo ripreso dopo ricaricamento pagina...';
                    document.getElementById('resume-notice').style.display = 'block';
                    
                    // Riavvia il monitoraggio dei risultati
                    isTestResumed = true;
                    resumeTestMonitoring();
                }
            })
            .catch(function(error) {
                console.log('Nessun test attivo da riprendere');
            });
        }

        // Controlla se c'è un test in corso al caricamento della pagina
        window.addEventListener('load', function() {
            // Aggiungi un delay per assicurarti che la pagina sia completamente caricata
            setTimeout(function() {
                // Prima controlla il localStorage
                const savedTest = localStorage.getItem('activeTest');
                if (savedTest) {
                    const testData = JSON.parse(savedTest);
                    // Verifica se il test è recente (meno di 10 minuti)
                    if (Date.now() - testData.startTime < 600000) {
                        document.getElementById('proxy-list').value = testData.proxies.join('\\n');
                        if (testData.maxWorkers) {
                            document.getElementById('max-workers').value = testData.maxWorkers;
                        }
                    }
                }
                
                // Poi controlla lo stato sul server
                checkSessionStatus();
            }, 500);
        });
    </script>
</body>
</html>
"""

# --- Backend Logic ---
URL_TO_TEST = 'https://new.newkso.ru/wind/'

def test_single_proxy(proxy_line, proxy_type, address_for_curl, session_id):
    """Test thread-safe per singolo proxy con speedtest"""
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
        
        # --- SPEEDTEST 5 secondi ---
        SPEEDTEST_URL = 'https://ash-speed.hetzner.com/10GB.bin'  # File pubblico per test velocità
        speedtest_cmd = [
            'curl', '-k', '--max-time', '5', '--silent', '--show-error', '--connect-timeout', '5',
            '--output', '-', '--limit-rate', '100m', SPEEDTEST_URL
        ]
        if proxy_type == 'socks5':
            speedtest_cmd.extend(['--socks5-hostname', address_for_curl])
        elif proxy_type == 'http':
            speedtest_cmd.extend(['--proxy', address_for_curl])

        start_time = time.time()
        speedtest_proc = subprocess.run(speedtest_cmd, capture_output=True, timeout=7)
        elapsed = time.time() - start_time
        bytes_downloaded = len(speedtest_proc.stdout)
        speed_mbps = round((bytes_downloaded * 8) / (elapsed * 1000 * 1000), 2) if elapsed > 0 else 0.0

        # Se errore nello speedtest, segnala ma considera comunque funzionante
        speedtest_error = None
        if speedtest_proc.returncode != 0:
            speedtest_error = speedtest_proc.stderr.decode(errors='ignore') if isinstance(speedtest_proc.stderr, bytes) else speedtest_proc.stderr

        result_dict = {
            'status': 'SUCCESS',
            'details': 'Connessione riuscita',
            'is_protocol_error': False,
            'protocol_used': proxy_type,
            'speedtest_mbps': speed_mbps,
            'speedtest_error': speedtest_error
        }
        return result_dict

    except subprocess.TimeoutExpired:
        return {'status': 'FAIL', 'details': 'Timeout script (15s)', 'is_protocol_error': False}
    except Exception as e:
        return {'status': 'FAIL', 'details': f'Errore esecuzione script: {e}', 'is_protocol_error': False}

def cleanup_abandoned_sessions():
    """Pulisce le sessioni abbandonate - versione migliorata"""
    current_time = datetime.now()
    abandoned_sessions = []
    
    with active_tests_lock:
        for session_id, info in active_tests.items():
            # Controlla sia il tempo di inizio che l'ultimo heartbeat
            last_activity = info.get('last_heartbeat', info['start_time'])
            time_since_activity = (current_time - last_activity).total_seconds()
            
            # Sessione abbandonata se:
            # - Più di 2 minuti senza heartbeat E test in corso
            # - Più di 10 minuti dall'inizio
            if (time_since_activity > 120 and info['running']) or time_since_activity > 600:
                abandoned_sessions.append(session_id)
        
        for session_id in abandoned_sessions:
            print(f"[{session_id[:8]}] Sessione abbandonata - ultimo heartbeat: {active_tests[session_id].get('last_heartbeat', 'mai')}")
            active_tests[session_id]['running'] = False
            del active_tests[session_id]

# Timer per pulizia automatica delle sessioni abbandonate
def start_cleanup_timer():
    cleanup_abandoned_sessions()
    threading.Timer(120, start_cleanup_timer).start()

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
    
    # Debug: stampa i dati ricevuti
    print(f"[DEBUG] Session ID: {session_id}")
    print(f"[DEBUG] Form data: {request.form}")
    
    proxy_list_str = request.form.get('proxies', '')
    max_workers = int(request.form.get('max_workers', 20))
    
    print(f"[DEBUG] Proxy list length: {len(proxy_list_str)}")
    print(f"[DEBUG] Max workers: {max_workers}")
    
    proxies = [line.strip() for line in proxy_list_str.split('\n') if line.strip()]

    if not proxies:
        print("[DEBUG] Nessun proxy trovato!")
        return Response("data: {\"error\": \"Nessun proxy fornito\"}\n\n", mimetype='text/event-stream')

    print(f"[DEBUG] Proxies parsed: {len(proxies)}")

    # Limita il numero di worker per evitare sovraccarico
    max_workers = min(max_workers, 50)
    max_workers = max(max_workers, 1)

    # Registra il test attivo
    with active_tests_lock:
        active_tests[session_id] = {
            'running': True,
            'start_time': datetime.now(),
            'last_heartbeat': datetime.now(),
            'total_proxies': len(proxies),
            'proxies': proxies,
            'current_index': 0,
            'completed_count': 0,
            'max_workers': max_workers
        }

    def test_proxy_wrapper(proxy_line):
        """Wrapper per testare un singolo proxy"""
        # Controlla se il test è ancora attivo
        with active_tests_lock:
            if session_id not in active_tests or not active_tests[session_id]['running']:
                return None
        
        result = None
        
        # Test del proxy con gestione protocolli
        if proxy_line.startswith(('socks5h://', 'socks5://')):
            proxy_address = proxy_line.split('//', 1)[1]
            result = test_single_proxy(proxy_line, 'socks5', proxy_address, session_id)
        elif proxy_line.startswith(('http://', 'https://')):
            result = test_single_proxy(proxy_line, 'http', proxy_line, session_id)
        else:
            # Prova prima come HTTP
            result_http = test_single_proxy(proxy_line, 'http', proxy_line, session_id)
            if result_http['status'] == 'SUCCESS':
                result = result_http
            elif result_http['status'] == 'STOPPED':
                result = result_http
            else:
                # Se fallisce, prova come SOCKS5
                result_socks = test_single_proxy(proxy_line, 'socks5', proxy_line, session_id)
                if result_socks['status'] == 'SUCCESS':
                    result = result_socks
                elif result_socks['status'] == 'STOPPED':
                    result = result_socks
                else:
                    result = result_http

        if result:
            result['proxy'] = proxy_line
            
            if result['status'] == 'SUCCESS':
                protocol_used = result.get('protocol_used', 'sconosciuto')
                proxy_to_save = proxy_line
                if protocol_used == 'http' and not proxy_line.startswith(('http://', 'https://')):
                    proxy_to_save = f"http://{proxy_line}"
                elif protocol_used == 'socks5' and not proxy_line.startswith(('socks5://', 'socks5h://')):
                    proxy_to_save = f"socks5://{proxy_line}"
                result['proxy_to_save'] = proxy_to_save
        
        return result

    def generate_results():
        try:
            # Numero di thread paralleli
            actual_workers = min(max_workers, len(proxies))
            print(f"[{session_id[:8]}] Avvio test parallelo con {actual_workers} worker per {len(proxies)} proxy")
            
            with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                # Invia tutti i proxy per il testing parallelo
                future_to_proxy = {executor.submit(test_proxy_wrapper, proxy): proxy for proxy in proxies}
                
                for future in as_completed(future_to_proxy):
                    # Controlla se il test è stato fermato
                    with active_tests_lock:
                        if session_id not in active_tests or not active_tests[session_id]['running']:
                            # Cancella tutti i future rimanenti
                            for f in future_to_proxy:
                                f.cancel()
                            break
                    
                    result = future.result()
                    if result and result['status'] != 'STOPPED':
                        # Aggiorna il contatore
                        with active_tests_lock:
                            if session_id in active_tests:
                                active_tests[session_id]['completed_count'] += 1
                        
                        print(f"[{session_id[:8]}] Risultato per {result['proxy']}: {result['status']}")
                        
                        try:
                            yield f"data: {json.dumps(result)}\n\n"
                        except GeneratorExit:
                            print(f"[{session_id[:8]}] Client disconnesso durante il test")
                            break
                        except Exception as e:
                            print(f"[{session_id[:8]}] Errore invio dati: {e}")
                            break
        
        except GeneratorExit:
            print(f"[{session_id[:8]}] Generatore interrotto")
        finally:
            # Pulisci sempre il test attivo
            with active_tests_lock:
                if session_id in active_tests:
                    active_tests[session_id]['running'] = False
                    del active_tests[session_id]
                    print(f"[{session_id[:8]}] Test parallelo pulito dopo disconnessione")
    
    return Response(generate_results(), mimetype='text/event-stream')

@app.route('/test/resume', methods=['POST'])
def resume_test_monitoring():
    """Riprende il monitoraggio di una sessione esistente"""
    data = request.get_json()
    session_id = data.get('session_id')
    
    with active_tests_lock:
        if session_id in active_tests and active_tests[session_id]['running']:
            # La sessione esiste ed è attiva
            test_info = active_tests[session_id]
            proxies = test_info['proxies']
            completed_count = test_info.get('completed_count', 0)
            max_workers = test_info.get('max_workers', 20)
            
            def generate_status():
                yield f"data: {{\"status\": \"RESUMED\", \"message\": \"Sessione parallela ripresa - {completed_count}/{len(proxies)} proxy già completati\"}}\n\n"
                
                # Continua il test parallelo per i proxy rimanenti
                remaining_proxies = proxies[completed_count:]
                if remaining_proxies:
                    def test_proxy_wrapper(proxy_line):
                        # Stesso wrapper del test principale
                        with active_tests_lock:
                            if session_id not in active_tests or not active_tests[session_id]['running']:
                                return None
                        
                        result = None
                        
                        if proxy_line.startswith(('socks5h://', 'socks5://')):
                            proxy_address = proxy_line.split('//', 1)[1]
                            result = test_single_proxy(proxy_line, 'socks5', proxy_address, session_id)
                        elif proxy_line.startswith(('http://', 'https://')):
                            result = test_single_proxy(proxy_line, 'http', proxy_line, session_id)
                        else:
                            result_http = test_single_proxy(proxy_line, 'http', proxy_line, session_id)
                            if result_http['status'] == 'SUCCESS':
                                result = result_http
                            elif result_http['status'] == 'STOPPED':
                                result = result_http
                            else:
                                result_socks = test_single_proxy(proxy_line, 'socks5', proxy_line, session_id)
                                if result_socks['status'] == 'SUCCESS':
                                    result = result_socks
                                elif result_socks['status'] == 'STOPPED':
                                    result = result_socks
                                else:
                                    result = result_http

                        if result:
                            result['proxy'] = proxy_line
                            
                            if result['status'] == 'SUCCESS':
                                protocol_used = result.get('protocol_used', 'sconosciuto')
                                proxy_to_save = proxy_line
                                if protocol_used == 'http' and not proxy_line.startswith(('http://', 'https://')):
                                    proxy_to_save = f"http://{proxy_line}"
                                elif protocol_used == 'socks5' and not proxy_line.startswith(('socks5://', 'socks5h://')):
                                    proxy_to_save = f"socks5://{proxy_line}"
                                result['proxy_to_save'] = proxy_to_save
                        
                        return result

                    actual_workers = min(max_workers, len(remaining_proxies))
                    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                        future_to_proxy = {executor.submit(test_proxy_wrapper, proxy): proxy for proxy in remaining_proxies}
                        
                        for future in as_completed(future_to_proxy):
                            with active_tests_lock:
                                if session_id not in active_tests or not active_tests[session_id]['running']:
                                    for f in future_to_proxy:
                                        f.cancel()
                                    break
                            
                            result = future.result()
                            if result and result['status'] != 'STOPPED':
                                with active_tests_lock:
                                    if session_id in active_tests:
                                        active_tests[session_id]['completed_count'] += 1

                                try:
                                    yield f"data: {json.dumps(result)}\n\n"
                                except GeneratorExit:
                                    break
                
                # Pulisci il test al completamento
                with active_tests_lock:
                    if session_id in active_tests:
                        active_tests[session_id]['running'] = False
                        del active_tests[session_id]
            
            return Response(generate_status(), mimetype='text/event-stream')
    
    return {'error': 'Sessione non trovata o non attiva'}, 404

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    """Endpoint per verificare che il client sia ancora connesso"""
    try:
        data = request.get_json(silent=True)
        session_id = data.get('session_id') if data else None
    except:
        session_id = None
    
    if not session_id:
        session_id = request.headers.get('X-Session-ID')
    
    if session_id:
        with active_tests_lock:
            if session_id in active_tests:
                # Aggiorna il timestamp dell'ultima attività
                active_tests[session_id]['last_heartbeat'] = datetime.now()
                return {'status': 'alive', 'session_id': session_id[:8]}
    
    return {'status': 'session_not_found'}, 404

@app.route('/stop', methods=['POST'])
def stop_test():
    """Endpoint migliorato per fermare un test in corso"""
    try:
        # Prova a leggere JSON
        data = request.get_json(silent=True)
        session_id = data.get('session_id') if data else None
        reason = data.get('reason', 'user_request') if data else 'user_request'
    except:
        session_id = None
        reason = 'user_request'
    
    if not session_id:
        session_id = request.headers.get('X-Session-ID') or session.get('session_id')
    
    if session_id:
        with active_tests_lock:
            if session_id in active_tests:
                active_tests[session_id]['running'] = False
                print(f"[{session_id[:8]}] Test parallelo fermato: {reason}")
                return {'status': 'stopped', 'session_id': session_id[:8], 'reason': reason}
    
    return {'status': 'session_not_found'}, 404

@app.route('/status/check', methods=['POST'])
def check_session_status():
    """Controlla se una sessione ha un test attivo"""
    try:
        data = request.get_json(silent=True)
        session_id = data.get('session_id') if data else None
    except:
        session_id = None
    
    if not session_id:
        session_id = request.headers.get('X-Session-ID') or session.get('session_id')
    
    if session_id:
        with active_tests_lock:
            if session_id in active_tests and active_tests[session_id]['running']:
                test_info = active_tests[session_id]
                return {
                    'test_running': True, 
                    'session_id': session_id[:8],
                    'completed_count': test_info.get('completed_count', 0),
                    'total_proxies': test_info.get('total_proxies', 0),
                    'max_workers': test_info.get('max_workers', 20)
                }
    
    return {'test_running': False}

@app.route('/status')
@require_auth
def get_status():
    """Endpoint protetto per ottenere lo stato dei test attivi"""
    with active_tests_lock:
        active_count = len(active_tests)
        tests_info = []
        for sid, info in active_tests.items():
            last_heartbeat = info.get('last_heartbeat')
            tests_info.append({
                'session_id': sid[:8],
                'full_session_id': sid,
                'running': info['running'],
                'start_time': info['start_time'].strftime('%H:%M:%S'),
                'start_date': info['start_time'].strftime('%Y-%m-%d'),
                'total_proxies': info['total_proxies'],
                'completed_count': info.get('completed_count', 0),
                'max_workers': info.get('max_workers', 20),
                'last_heartbeat': last_heartbeat.strftime('%H:%M:%S') if last_heartbeat else 'mai'
            })
    
    return {
        'active_tests': active_count,
        'tests': tests_info,
        'server_info': {
            'version': '2.2',
            'multi_user': True,
            'resume_support': True,
            'heartbeat_support': True,
            'parallel_testing': True,
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
        <title>Admin Panel - Proxy Tester Parallelo</title>
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
            .progress { font-size: 0.9em; color: #666; }
            .heartbeat { font-size: 0.8em; color: #888; }
            .workers { font-size: 0.8em; color: #007bff; font-weight: bold; }
            .parallel-badge { background: #4caf50; color: white; padding: 2px 6px; border-radius: 3px; font-size: 0.7em; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Admin Panel - Proxy Tester Parallelo</h1>
            <div class="status-box">
                <h3>Stato Server</h3>
                <p><strong>Versione:</strong> 2.2 Multi-User con Testing Parallelo <span class="parallel-badge">PARALLELO</span></p>
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
                            <th>Progresso</th>
                            <th>Workers</th>
                            <th>Avviato</th>
                            <th>Data</th>
                            <th>Ultimo Heartbeat</th>
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
                .then(function(response) { return response.json(); })
                .then(function(data) {
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
                        data.tests.forEach(function(test) {
                            const row = document.createElement('tr');
                            const statusClass = test.running ? 'running' : 'stopped';
                            const statusText = test.running ? '🟢 Attivo' : '🔴 Fermato';
                            const progress = test.completed_count + '/' + test.total_proxies;
                            const workers = test.max_workers || 'N/A';
                            
                            row.innerHTML = '<td><code>' + test.session_id + '</code></td>' +
                                          '<td><span class="' + statusClass + '">' + statusText + '</span></td>' +
                                          '<td><span class="progress">' + progress + '</span></td>' +
                                          '<td><span class="workers">' + workers + ' thread</span></td>' +
                                          '<td>' + test.start_time + '</td>' +
                                          '<td>' + test.start_date + '</td>' +
                                          '<td><span class="heartbeat">' + test.last_heartbeat + '</span></td>';
                            sessionsTableBody.appendChild(row);
                        });
                    } else {
                        // Mostra messaggio
                        sessionsTable.style.display = 'none';
                        sessionsList.style.display = 'block';
                        sessionsList.innerHTML = '<p>🎉 Nessuna sessione attiva</p>';
                    }
                })
                .catch(function(error) {
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
    print("🚀 Avvio del server Proxy Tester Web Multi-Utente con Testing Parallelo...")
    print("Apri http://127.0.0.1:7860 nel tuo browser.")
    print("Admin panel: http://127.0.0.1:7860/admin")
    print("Status API: http://127.0.0.1:7860/status")
    print(f"Admin password: {os.getenv('ADMIN_PASSWORD', 'admin123')}")
    print("✨ Novità: Testing parallelo per velocità massima!")
    
    # Avvia il timer di pulizia automatica
    start_cleanup_timer()
    
    app.run(host='0.0.0.0', port=7860, debug=False, threaded=True)
