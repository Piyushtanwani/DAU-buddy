// Global callback for Google Sign-In, declared outside DOMContentLoaded to ensure it's available for GSI
window.handleCredentialResponse = (response) => {
    if (window.processLogin) {
        window.processLogin(response);
    } else {
        // Fallback in case the callback fires before DOMContentLoaded completes
        document.addEventListener("DOMContentLoaded", () => {
            if (window.processLogin) window.processLogin(response);
        });
    }
};

// Redirect unauthenticated users to the login page
(function () {
    const session = localStorage.getItem("dau_buddy_auth");
    if (!session) {
        window.location.href = "/?view=login";
        return;
    }
    try {
        const authData = JSON.parse(session);
        if (!authData.email || !authData.credential) {
            window.location.href = "/?view=login";
            return;
        }
    } catch (e) {
        window.location.href = "/?view=login";
        return;
    }
})();

document.addEventListener("DOMContentLoaded", () => {
    // ── Google OAuth & Session Management ─────────────────────────────────────
    const loginOverlay = document.getElementById("login-overlay");
    const appContainer = document.getElementById("app-container");
    const loginError = document.getElementById("login-error");
    const welcomeName = document.getElementById("welcome-name");
    const logoutBtn = document.getElementById("logout-btn");
    const apiKeyInput = document.getElementById("api-key-input");
    const regenerateBtn = document.getElementById("regenerate-key-btn");
    const configCode = document.getElementById("codeBlock");

    const dropdownName = document.getElementById("dropdown-name");
    const dropdownEmail = document.getElementById("dropdown-email");
    const dropdownAvatar = document.getElementById("dropdown-avatar");
    const navProfileTrigger = document.getElementById("nav-profile-trigger");
    const dropdownRole = document.getElementById("dropdown-role");
    const profileDropdown = document.getElementById("profile-dropdown");
    const profileContainer = document.getElementById("profile-container");

    const landingProfileContainer = document.getElementById("landing-profile-container");
    const landingProfileTrigger = document.getElementById("landing-profile-trigger");
    const landingProfileDropdown = document.getElementById("landing-profile-dropdown");
    const landingDropdownAvatar = document.getElementById("landing-dropdown-avatar");
    const landingDropdownName = document.getElementById("landing-dropdown-name");
    const landingDropdownEmail = document.getElementById("landing-dropdown-email");
    const landingDropdownRole = document.getElementById("landing-dropdown-role");
    const landingLogoutBtn = document.getElementById("landing-logout-btn");


    function setApiKeyValue(val) {
        if (apiKeyInput) {
            apiKeyInput.value = val;
        }
    }

    function updateMaintainerDashboardVisibility(role) {
        const dashboardBtn = document.getElementById("nav-dashboard-btn");
        if (dashboardBtn) {
            if (role && role.includes("Maintainer")) {
                dashboardBtn.style.display = "flex";
            } else {
                dashboardBtn.style.display = "none";
            }
        }
    }

    async function checkExistingKey(credential) {
        // [Lines truncated for replace block; we will replace from the start of the file down to the old handleCredentialResponse]
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000);
            const response = await fetch("/api/me", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: credential }),
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            if (response.ok) {
                const data = await response.json();

                // ALWAYS update the role if the API provides it
                if (dropdownRole || landingDropdownRole) {
                    const role = data.role || "User";
                    if (dropdownRole) dropdownRole.textContent = role;
                    if (landingDropdownRole) landingDropdownRole.textContent = role;
                    const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                    authData.role = role;
                    localStorage.setItem("dau_buddy_auth", JSON.stringify(authData));
                    updateMaintainerDashboardVisibility(role);
                }

                if (data.has_key) {
                    const key = data.api_key;
                    if (key) {
                        if (apiKeyInput.value === "Loading..." || apiKeyInput.value.includes("Please")) {
                            setApiKeyValue(key);
                            updateConfigSnippet(key);
                        }
                    }
                    if (data.key_prefix) {
                        const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                        authData.key_prefix = data.key_prefix;
                        localStorage.setItem("dau_buddy_auth", JSON.stringify(authData));
                    }
                    return { hasKey: true, prefix: data.key_prefix };
                }
            } else if (response.status === 429) {
                return { rateLimited: true };
            } else if (response.status === 401) {
                // Token expired or invalid
                localStorage.removeItem("dau_buddy_auth");
                window.location.reload();
            }
        } catch (e) {
            console.error("Error checking key", e);
        }
        return false;
    }

    async function generateKey(credential, regenerate = false) {
        try {
            setApiKeyValue("Generating...");
            if (regenerateBtn) {
                regenerateBtn.disabled = true;
                regenerateBtn.textContent = "Generating...";
            }

            if (!credential) {
                alert("Error: Missing Google credential in frontend. Please login again.");
                return;
            }

            const endpoint = regenerate ? "/api/regenerate-key" : "/api/generate-key";
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: credential })
            });
            if (response.ok) {
                const data = await response.json();
                const key = data.api_key;

                // Show modal with new key
                const newKeyModal = document.getElementById("new-key-modal");
                const newKeyInput = document.getElementById("new-key-input");
                if (newKeyModal && newKeyInput) {
                    newKeyInput.value = key;
                    newKeyModal.style.display = "flex";
                }

                // Mask the key on main UI
                const maskedKey = (data.key_prefix || key.substring(0, 14)) + "••••••••••••••••••••••••••••••••";
                setApiKeyValue(maskedKey);

                updateConfigSnippet(maskedKey);
                if (dropdownRole || landingDropdownRole) {
                    const role = data.role || "User";
                    if (dropdownRole) dropdownRole.textContent = role;
                    if (landingDropdownRole) landingDropdownRole.textContent = role;

                    const updatedAuth = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                    updatedAuth.role = role;
                    updatedAuth.key_prefix = key.substring(0, 14);
                    localStorage.setItem("dau_buddy_auth", JSON.stringify(updatedAuth));
                    updateMaintainerDashboardVisibility(role);
                }
            } else {
                if (response.status === 401) {
                    alert("Session expired. Please login again.");
                    localStorage.removeItem("dau_buddy_auth");
                    window.location.reload();
                    return;
                }
                const err = await response.json();
                const errMsg = (typeof err.detail === 'object') ? JSON.stringify(err.detail) : (err.detail || "Error generating key.");
                setApiKeyValue(errMsg);
                alert("API Error: " + errMsg);
            }
        } catch (e) {
            console.error(e);
            setApiKeyValue("Error generating key.");
            alert("Frontend Error: " + e.message);
        } finally {
            if (regenerateBtn) {
                regenerateBtn.disabled = false;
                regenerateBtn.textContent = "Regenerate Key";
            }
        }
    }

    let pythonPath = "python";
    let projectPath = "E:\\\\MCP Project";

    // Fetch local paths dynamically on startup
    fetch("/api/config-info")
        .then(res => res.json())
        .then(data => {
            if (data.python_path) pythonPath = data.python_path;
            if (data.project_path) projectPath = data.project_path;
            // If there's an existing placeholder, update the snippet
            if (apiKeyInput.value && !apiKeyInput.value.startsWith("Generating") && !apiKeyInput.value.startsWith("Error")) {
                updateConfigSnippet(apiKeyInput.value);
            }
        })
        .catch(err => console.error("Error fetching config info:", err));


    let currentApp = 'claude';
    let currentKey = 'YOUR_API_KEY_HERE';

    window.config = function () {
        const baseUrl = window.location.origin + "/mcp/sse";
        const displayKey = (currentKey.includes('••••') || currentKey === 'YOUR_API_KEY_HERE') ? '<YOUR_API_KEY>' : currentKey;

        if (currentApp === 'claude') {
            return '{' + '\n' +
                '  "mcpServers": {' + '\n' +
                '    "DAU Buddy": {' + '\n' +
                '      "command": "npx",' + '\n' +
                '      "args": [' + '\n' +
                '        "-y", "mcp-remote",' + '\n' +
                '        "' + baseUrl + '",' + '\n' +
                '        "--allow-http",' + '\n' +
                '        "--transport", "sse-only",' + '\n' +
                '        "--header", "Authorization:${AUTH_HEADER}",' + '\n' +
                '        "--header", "X-Client-Name:Claude"' + '\n' +
                '      ],' + '\n' +
                '      "env": { "AUTH_HEADER": "Bearer ' + displayKey + '" }' + '\n' +
                '    }' + '\n' +
                '  }' + '\n' +
                '}';
        } else if (currentApp === 'cursor') {
            return '{' + '\n' +
                '  "mcpServers": {' + '\n' +
                '    "DAU Buddy": {' + '\n' +
                '      "type": "sse",' + '\n' +
                '      "url": "' + baseUrl + '",' + '\n' +
                '      "headers": {' + '\n' +
                '        "Authorization": "Bearer ' + displayKey + '",' + '\n' +
                '        "X-Client-Name": "Cursor/Windsurf"' + '\n' +
                '      }' + '\n' +
                '    }' + '\n' +
                '  }' + '\n' +
                '}';
        } else if (currentApp === 'opencode') {
            return '{' + '\n' +
                '  "mcpServers": {' + '\n' +
                '    "DAU Buddy": {' + '\n' +
                '      "type": "remote",' + '\n' +
                '      "url": "' + baseUrl + '",' + '\n' +
                '      "headers": {' + '\n' +
                '        "Authorization": "Bearer ' + displayKey + '",' + '\n' +
                '        "X-Client-Name": "OpenCode"' + '\n' +
                '      }' + '\n' +
                '    }' + '\n' +
                '  }' + '\n' +
                '}';
        } else if (currentApp === 'codex') {
            return '[mcp_servers.dau-buddy]' + '\n' +
                'command = "npx"' + '\n' +
                'args = [' + '\n' +
                '  "-y",' + '\n' +
                '  "mcp-remote",' + '\n' +
                '  "' + baseUrl + '",' + '\n' +
                '  "--allow-http",' + '\n' +
                '  "--transport",' + '\n' +
                '  "sse-only",' + '\n' +
                '  "--header",' + '\n' +
                '  "Authorization:${AUTH_HEADER}",' + '\n' +
                '  "--header",' + '\n' +
                '  "X-Client-Name:Codex"' + '\n' +
                ']' + '\n' +
                'env = { "AUTH_HEADER" = "Bearer ' + displayKey + '" }';
        }
        return '';
    }

    function updateConfigSnippet(key) {
        currentKey = key;
        const cb = document.getElementById('codeBlock');
        if (cb) cb.textContent = window.config();

        // Also update the key display
        const display = document.getElementById('api-key-display');
        if (display && key !== 'YOUR_API_KEY_HERE') {
            if (key.includes('••••')) {
                const parts = key.split('••••');
                display.innerHTML = '<span>' + parts[0] + '</span><span class="dots">' + '•••••••••••••••••••••••••' + '</span>';
            } else {
                display.textContent = key;
            }
        }
    }
    let currentCredential = null;
    let currentEmail = null;

    async function showWelcomeScreen(name, email, picture, credential = null, cachedKey = null, autoShowDashboard = true) {
        currentEmail = email;
        if (credential) currentCredential = credential;

        if (autoShowDashboard) {
            // Hide landing page and login overlay
            const landingView = document.getElementById("landing-view");
            if (landingView) landingView.style.display = "none";

            if (loginOverlay) loginOverlay.style.opacity = "0";
            if (loginOverlay) loginOverlay.style.display = "none";
            if (appContainer) appContainer.style.display = "block";
            localStorage.setItem("dau_buddy_view", "dashboard");
        }

        let displayName = name || "User";
        if (name) {
            // If the display name is purely numeric (e.g. "2025 12063"), use the email local part instead
            const firstName = name.split(" ")[0];
            displayName = /^\d+$/.test(firstName) ? email.split("@")[0] : firstName;
        }
        if (welcomeName) welcomeName.textContent = `Welcome, ${displayName}!`;
        if (dropdownName) dropdownName.textContent = displayName;
        if (dropdownEmail) dropdownEmail.textContent = email;
        if (landingDropdownName) landingDropdownName.textContent = displayName;
        if (landingDropdownEmail) landingDropdownEmail.textContent = email;

        if (picture) {
            if (dropdownAvatar) dropdownAvatar.src = picture;
            if (navProfileTrigger) navProfileTrigger.src = picture;
            if (landingDropdownAvatar) landingDropdownAvatar.src = picture;
            if (landingProfileTrigger) landingProfileTrigger.src = picture;
        }

        // Determine role: use cached role from localStorage first, fall back to email-based guess
        if ((dropdownRole || landingDropdownRole) && email) {
            const cachedAuth = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
            let role = cachedAuth.role || "User";
            if (!cachedAuth.role) {
                // No cached role, guess from email pattern
                if (email.endsWith("@dau.ac.in")) {
                    const localPart = email.split("@")[0];
                    if (/^\d+$/.test(localPart)) {
                        role = "Student";
                    } else {
                        role = "Faculty/Staff";
                    }
                }
            }
            if (dropdownRole) dropdownRole.textContent = role;
            if (landingDropdownRole) landingDropdownRole.textContent = role;
            updateMaintainerDashboardVisibility(role);
        }

        let activeKey = cachedKey;

        // Only use activeKey if it's an actual hex key
        if (activeKey && activeKey !== "Loading..." && activeKey !== "No API Key Generated" && activeKey !== "No key exists. Please generate.") {
            setApiKeyValue(activeKey);
            updateConfigSnippet(activeKey);
            if (regenerateBtn) regenerateBtn.textContent = "Regenerate Key";

            // Restore role if saved
            const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
            if (authData.role && (dropdownRole || landingDropdownRole)) {
                if (dropdownRole) dropdownRole.textContent = authData.role;
                if (landingDropdownRole) landingDropdownRole.textContent = authData.role;
                updateMaintainerDashboardVisibility(authData.role);
            }

            // Sync status/role in background if we have credential
            if (currentCredential) {
                checkExistingKey(currentCredential);
            }
        } else if (currentCredential) {
            const result = await checkExistingKey(currentCredential);
            if (result && result.rateLimited) {
                setApiKeyValue("Rate limit exceeded. Please wait a minute.");
                if (regenerateBtn) regenerateBtn.textContent = "Wait & Refresh";
                updateConfigSnippet("YOUR_API_KEY_HERE");
            } else {
                const hasKey = result && result.hasKey;
                if (!hasKey) {
                    setApiKeyValue("No API Key Generated");
                    if (regenerateBtn) regenerateBtn.textContent = "Generate Key";
                    updateConfigSnippet("YOUR_API_KEY_HERE");
                } else {
                    if (regenerateBtn) {
                        regenerateBtn.textContent = "Regenerate Key";
                    }
                    if (result.prefix) {
                        const maskedKey = result.prefix + "••••••••••••••••••••••••••••••••";
                        setApiKeyValue(maskedKey);
                        updateConfigSnippet(maskedKey);
                    } else {
                        setApiKeyValue("Key exists but is not cached. Please regenerate.");
                        updateConfigSnippet("YOUR_API_KEY_HERE");
                    }
                }
            }
        } else {
            // Should not happen, but fallback
            setApiKeyValue("Please Login Again");
            if (dropdownRole) dropdownRole.textContent = "";
            if (landingDropdownRole) landingDropdownRole.textContent = "";
        }

        if (regenerateBtn) {
            regenerateBtn.onclick = async () => {
                if (regenerateBtn.textContent.includes("Wait & Refresh")) {
                    window.location.reload();
                    return;
                }
                const isRegenerating = regenerateBtn.textContent.includes("Regenerate") || regenerateBtn.textContent.includes("Generating");
                await generateKey(currentCredential, isRegenerating);
            };
        }
    }
    // Handle URL parameters for view routing from external pages (like docs.html)
    const urlParams = new URLSearchParams(window.location.search);
    const viewParam = urlParams.get('view');
    if (viewParam === 'landing' || viewParam === 'dashboard') {
        localStorage.setItem("dau_buddy_view", viewParam);
        // Clean up the URL so refresh works normally
        window.history.replaceState({}, document.title, window.location.pathname);
    } else if (viewParam === 'login') {
        localStorage.setItem("dau_buddy_view", "landing");
        window.history.replaceState({}, document.title, window.location.pathname);
        // Wait just a tiny bit for the UI to be ready
        setTimeout(() => {
            const loginOverlay = document.getElementById("login-overlay");
            if (loginOverlay) {
                if (loginOverlay) loginOverlay.style.display = "flex";
                setTimeout(() => { if (loginOverlay) loginOverlay.style.opacity = "1"; }, 10);
            }
        }, 100);
    }

    // Check if user is already logged in
    const storedSession = localStorage.getItem("dau_buddy_auth");
    if (storedSession) {
        try {
            const authData = JSON.parse(storedSession);
            if (authData.email && authData.credential) {
                // Determine which view to show based on last state
                const currentView = localStorage.getItem("dau_buddy_view");
                const shouldShowDashboard = (currentView === "dashboard");

                // Valid session exists, configure UI
                showWelcomeScreen(authData.name, authData.email, authData.picture, authData.credential, authData.api_key, shouldShowDashboard);

                // Update landing page buttons to indicate they lead to the dashboard
                const btnSignIn = document.getElementById("nav-signin-btn");
                const btnGetStarted = document.getElementById("hero-get-started-btn");
                if (btnSignIn) {
                    if (btnSignIn) btnSignIn.textContent = "Dashboard";
                    if (landingProfileContainer) landingProfileContainer.style.display = "block";
                }
                if (btnGetStarted) btnGetStarted.textContent = "Go to Dashboard";
            }
        } catch (e) {
            console.error("Invalid auth session data", e);
            localStorage.removeItem("dau_buddy_auth");
        }
    }

    // Global callback for Google Sign-In
    window.processLogin = (response) => {
        try {
            // Decode JWT token payload (middle part)
            const payloadBase64 = response.credential.split('.')[1];
            const decodedPayload = JSON.parse(atob(payloadBase64.replace(/-/g, '+').replace(/_/g, '/')));

            const email = decodedPayload.email;

            if (email) {
                // Successful login
                localStorage.setItem("dau_buddy_auth", JSON.stringify({
                    email: email,
                    name: decodedPayload.name,
                    picture: decodedPayload.picture,
                    credential: response.credential
                }));
                loginError.style.display = "none";

                // Update landing page buttons immediately
                const btnSignIn = document.getElementById("nav-signin-btn");
                const btnGetStarted = document.getElementById("hero-get-started-btn");
                if (btnSignIn) {
                    if (btnSignIn) btnSignIn.textContent = "Dashboard";
                    if (landingProfileContainer) landingProfileContainer.style.display = "block";
                }
                if (btnGetStarted) btnGetStarted.textContent = "Go to Dashboard";

                // Fade out overlay
                if (loginOverlay) loginOverlay.style.opacity = "0";
                setTimeout(() => {
                    if (loginOverlay) loginOverlay.style.display = "none";
                    showWelcomeScreen(decodedPayload.name, email, decodedPayload.picture, response.credential);
                }, 400);
            } else {
                // Unauthorized domain
                loginError.style.display = "flex";
            }
        } catch (error) {
            console.error("Error decoding Google JWT:", error);
            loginError.style.display = "flex";
            loginError.querySelector("span").textContent = "Error authenticating. Please try again.";
        }
    };

    // Logout handling
    const handleLogout = () => {
        localStorage.removeItem("dau_buddy_auth");
        localStorage.removeItem("dau_buddy_view");
        window.location.href = "/";
    };
    if (logoutBtn) logoutBtn.addEventListener("click", handleLogout);
    if (landingLogoutBtn) landingLogoutBtn.addEventListener("click", handleLogout);
    const btnGetStarted = document.getElementById("hero-get-started-btn");
    const btnSignIn = document.getElementById("nav-signin-btn");
    const btnCloseLogin = document.getElementById("close-login-btn");
    const homeBtn = document.getElementById("home-btn");

    if (homeBtn) {
        if (homeBtn) homeBtn.addEventListener("click", () => {
            if (appContainer) appContainer.style.display = "none";
            const landingView = document.getElementById("landing-view");
            if (landingView) landingView.style.display = "block";
            localStorage.setItem("dau_buddy_view", "landing");
        });
    }

    function openLoginModal() {
        const storedSession = localStorage.getItem("dau_buddy_auth");
        if (storedSession) {
            try {
                const authData = JSON.parse(storedSession);
                if (authData.email && authData.credential) {
                    // Already logged in, just switch back to dashboard
                    const landingView = document.getElementById("landing-view");
                    if (landingView) landingView.style.display = "none";
                    if (appContainer) appContainer.style.display = "block";
                    localStorage.setItem("dau_buddy_view", "dashboard");
                    return;
                }
            } catch (e) { }
        }

        if (loginOverlay) loginOverlay.style.display = "flex";
        setTimeout(() => { if (loginOverlay) loginOverlay.style.opacity = "1"; }, 10);
    }

    function closeLoginModal() {
        if (loginOverlay) loginOverlay.style.opacity = "0";
        setTimeout(() => { if (loginOverlay) loginOverlay.style.display = "none"; }, 300);
    }

    if (btnGetStarted) btnGetStarted.addEventListener("click", openLoginModal);
    if (btnSignIn) btnSignIn.addEventListener("click", openLoginModal);
    if (btnCloseLogin) btnCloseLogin.addEventListener("click", closeLoginModal);


    // Wizard Logic
    var OS = (function () {
        var p = navigator.platform.toLowerCase(), u = navigator.userAgent.toLowerCase();
        if (p.indexOf('mac') > -1 || u.indexOf('mac') > -1) return { name: 'Mac', path: '~/Library/Application Support/Claude/claude_desktop_config.json' };
        if (p.indexOf('linux') > -1) return { name: 'Linux', path: '~/.config/Claude/claude_desktop_config.json' };
        return { name: 'Windows', path: '%APPDATA%\\Claude\\claude_desktop_config.json' };
    })();
    const osEl = document.getElementById('osName');
    if (osEl) osEl.textContent = OS.name;

    window.pickApp = function (el) {
        document.querySelectorAll('.setup-app').forEach(function (a) { a.classList.remove('selected') });
        el.classList.add('selected');
        var name = el.querySelector('.setup-app-name').textContent;
        const appLabel = document.getElementById('appLabel');
        if (appLabel) appLabel.textContent = name;

        currentApp = el.getAttribute('data-app');
        updateConfigSnippet(currentKey); // Refresh code block

        // Update config file name dynamically
        let configName = 'your config file';
        if (currentApp === 'claude') configName = 'claude_desktop_config.json';
        else if (currentApp === 'cursor') configName = 'mcp.json';
        else if (currentApp === 'opencode') configName = 'opencode.json';
        else if (currentApp === 'codex') configName = 'config.toml';
        
        const configFileNameEl = document.getElementById('configFileName');
        if (configFileNameEl) {
            configFileNameEl.innerHTML = '<b style="font-family:var(--setup-mono);">' + configName + '</b>';
        }

        const readyAppNameEl = document.getElementById('readyAppName');
        if (readyAppNameEl) readyAppNameEl.textContent = name;

        const readyAppExampleEl = document.getElementById('readyAppExample');
        if (readyAppExampleEl) {
            if (currentApp === 'claude') readyAppExampleEl.textContent = 'E.g. "When are the next midsem dates?"';
            else if (currentApp === 'cursor') readyAppExampleEl.textContent = 'E.g. "Who is the professor for Data Structures?"';
            else if (currentApp === 'opencode') readyAppExampleEl.textContent = 'E.g. "Show me the upcoming holidays."';
            else if (currentApp === 'codex') readyAppExampleEl.textContent = 'E.g. "Can you check the timetable for my program?"';
        }

        // Toggle Node.js step
        const nodejsStep = document.getElementById('step-nodejs');
        if (nodejsStep) {
            if (currentApp === 'claude' || currentApp === 'codex') {
                nodejsStep.style.display = 'flex';
                const nodeMarker = document.getElementById('nodejs-marker');
                if (nodeMarker) nodeMarker.classList.remove('done');
                if (nodeMarker) nodeMarker.innerHTML = '1';
                // Adjust other numbers
                document.querySelectorAll('.setup-step-marker').forEach((m, i) => {
                    if (m.id !== 'nodejs-marker' && !m.classList.contains('done')) {
                        m.textContent = i + 1;
                    }
                });
            } else {
                nodejsStep.style.display = 'none';
                let counter = 1;
                document.querySelectorAll('.setup-step-marker').forEach((m) => {
                    if (m.id !== 'nodejs-marker') {
                        if (!m.parentElement.classList.contains('done')) {
                            m.textContent = counter;
                        }
                        counter++;
                    }
                });
            }
        }

        // Update path info
        const whereNote = document.getElementById('whereNote');
        if (whereNote && whereNote.style.display === 'block') {
            toggleWhere();
            toggleWhere(); // to re-render
        }
    }

    window.copyConfig = function () {
        var text = window.config();
        navigator.clipboard.writeText(text).then(function () { ok() }, function () {
            var t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select();
            try { document.execCommand('copy'); ok() } catch (e) { toastSetup('Copy failed — select the config manually') }
            document.body.removeChild(t);
        });
        function ok() {
            var b = document.getElementById('copyBtn');
            b.innerHTML = '<i class="fa-solid fa-check"></i> Copied';
            setTimeout(function () { b.innerHTML = '<i class="fa-regular fa-copy"></i> Copy config' }, 2200);
            toastSetup('Config copied to clipboard');

            // Mark step as done
            const step = b.closest('.setup-step');
            if (step) {
                step.classList.add('done');
                const marker = step.querySelector('.setup-step-marker');
                if (marker) marker.innerHTML = '<i class="fa-solid fa-check"></i>';
            }
        }
    }

    window.toggleCode = function () {
        var w = document.getElementById('codeWrap'), l = document.getElementById('peekLink');
        var open = w.style.display === 'none';
        w.style.display = open ? 'block' : 'none';
        l.textContent = open ? 'Hide the config' : 'Show the config';
    }

    window.toggleWhere = function () {
        var n = document.getElementById('whereNote');
        if (n.style.display === 'none') {
            n.style.display = 'block';
            let path = '';
            if (currentApp === 'claude') path = OS.path;
            else if (currentApp === 'cursor') path = 'Settings > Features > MCP';
            else if (currentApp === 'opencode') path = 'Settings > OpenCode > MCP Servers';
            else if (currentApp === 'codex') path = '~/.codex/config.toml';
            n.innerHTML = 'Location: <b style="font-family:var(--setup-mono);font-size:12px">' + path + '</b>';
        } else { n.style.display = 'none'; }
    }

    window.markNodejsDone = function() {
        const step = document.getElementById('step-nodejs');
        if (step) {
            step.classList.add('done');
            const marker = step.querySelector('.setup-step-marker');
            if (marker) marker.innerHTML = '<i class="fa-solid fa-check"></i>';
        }
    }

    window.openDownload = function (app) {
        let url = '';
        if (app === 'claude') url = 'https://claude.ai/download';
        else if (app === 'cursor') url = 'https://cursor.com';
        else if (app === 'nodejs') url = 'https://nodejs.org/en/download';
        else if (app === 'opencode') url = 'https://opencode.ai/download';
        else if (app === 'codex-windows') url = 'https://chatgpt.com/download';
        else if (app === 'codex-linux') url = 'https://www.npmjs.com/search?q=codex-cli';

        if (url) {
            window.open(url, '_blank');
        } else {
            toastSetup('Download page for ' + app + ' is not available.');
        }

        // Mark node step as done if node was clicked
        if (app === 'nodejs') {
            const step = document.getElementById('step-nodejs');
            if (step) {
                step.classList.add('done');
                const marker = step.querySelector('.setup-step-marker');
                if (marker) marker.innerHTML = '<i class="fa-solid fa-check"></i>';
            }
        }
    }

    var toastTimer;
    window.toastSetup = function (m) {
        var t = document.getElementById('setup-toast');
        if (!t) return;
        t.textContent = m; t.classList.add('show');
        clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove('show') }, 1800);
    }

    // Open config button
    const openConfigBtn = document.getElementById('openConfigBtn');
    if (openConfigBtn) {
        openConfigBtn.addEventListener('click', function () {
            toastSetup('Opening config folder...');
            fetch('/api/open-config-folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ app: currentApp })
            }).then(res => res.json()).then(data => {
                if (data.status === 'success') {
                    toastSetup('Config folder opened');
                    // Mark step as done
                    const step = openConfigBtn.closest('.setup-step');
                    if (step) {
                        step.classList.add('done');
                        const marker = step.querySelector('.setup-step-marker');
                        if (marker) marker.innerHTML = '<i class="fa-solid fa-check"></i>';
                    }
                } else {
                    toastSetup('Could not open folder directly. You may need to open it manually.');
                }
            }).catch(e => {
                console.error(e);
                toastSetup('Could not open folder directly. You may need to open it manually.');
            });
        });
    }

    // ── Feedback System ────────────────────────────────────────────────────────

    const feedbackBtn = document.getElementById("feedback-btn");
    const feedbackModal = document.getElementById("feedback-modal");
    const closeFeedbackBtn = document.getElementById("close-feedback-btn");
    const cancelFeedbackBtn = document.getElementById("cancel-feedback-btn");
    const feedbackForm = document.getElementById("feedback-form");
    const feedbackDesc = document.getElementById("feedback-description");
    const charCount = document.getElementById("char-count");
    const submitFeedbackBtn = document.getElementById("submit-feedback-btn");
    const submitText = submitFeedbackBtn?.querySelector(".submit-text");
    const loader = submitFeedbackBtn?.querySelector(".loader");
    const toastContainer = document.getElementById("toast-container");

    function showToast(message, type = "success") {
        if (!toastContainer) return;
        const toast = document.createElement("div");
        toast.className = `toast ${type}`;
        toast.innerHTML = type === "success"
            ? `<i class="fa-solid fa-circle-check"></i> <span>${message}</span>`
            : `<i class="fa-solid fa-circle-exclamation"></i> <span>${message}</span>`;

        toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = "slideInRight 0.3s ease-in reverse forwards";
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    if (feedbackBtn && feedbackModal) {
        if (feedbackBtn) feedbackBtn.addEventListener("click", () => {
            feedbackModal.style.display = "flex";
            document.body.style.overflow = "hidden";
        });

        const closeModal = () => {
            feedbackModal.style.display = "none";
            document.body.style.overflow = "";
            feedbackForm.reset();
            charCount.textContent = "0";
            charCount.parentElement.classList.remove("limit-reached");
        };

        if (closeFeedbackBtn) closeFeedbackBtn.addEventListener("click", closeModal);
        if (cancelFeedbackBtn) cancelFeedbackBtn.addEventListener("click", closeModal);
        if (feedbackModal) feedbackModal.addEventListener("click", (e) => {
            if (e.target === feedbackModal) closeModal();
        });

        if (feedbackDesc && charCount) {
            if (feedbackDesc) feedbackDesc.addEventListener("input", (e) => {
                const len = e.target.value.length;
                charCount.textContent = len;
                if (len >= 1000) {
                    charCount.parentElement.classList.add("limit-reached");
                } else {
                    charCount.parentElement.classList.remove("limit-reached");
                }
            });
        }

        let isSubmittingFeedback = false;
        if (feedbackForm) {
            feedbackForm.addEventListener("submit", async (e) => {
                e.preventDefault();
                if (isSubmittingFeedback) return;

                const category = document.getElementById("feedback-category").value;
                const subject = document.getElementById("feedback-subject").value.trim();
                const description = feedbackDesc.value.trim();

                if (!category || !subject || !description) {
                    showToast("Please fill in all required fields.", "error");
                    return;
                }

                // Get current Google credential
                const authSession = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                const currentCredential = authSession.credential;

                if (!currentCredential) {
                    showToast("Session not found. Please log in again.", "error");
                    return;
                }

                isSubmittingFeedback = true;
                submitFeedbackBtn.disabled = true;
                if (submitText) submitText.style.display = "none";
                if (loader) loader.style.display = "block";

                try {
                    const response = await fetch("/api/feedback", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ category, subject, description, credential: currentCredential })
                    });

                    if (response.ok) {
                        closeModal();
                        showToast("Thank you! Your feedback has been submitted.");
                    } else {
                        const errorData = await response.json();
                        showToast(errorData.detail || "Failed to submit feedback.", "error");
                    }
                } catch (error) {
                    console.error("Feedback error:", error);
                    showToast("An error occurred. Please try again.", "error");
                } finally {
                    isSubmittingFeedback = false;
                    submitFeedbackBtn.disabled = false;
                    if (submitText) submitText.style.display = "block";
                    if (loader) loader.style.display = "none";
                }
            });
        }
    }
    const newKeyModal = document.getElementById("new-key-modal");
    const newKeyInput = document.getElementById("new-key-input");
    const copyNewKeyBtn = document.getElementById("copy-new-key-btn");
    const closeNewKeyModal = document.getElementById("close-new-key-modal");
    const doneNewKeyBtn = document.getElementById("done-new-key-btn");

    function closeKeyModal() {
        if (newKeyModal) {
            newKeyModal.style.display = "none";
            // Clear the input in the modal so it can't be inspected easily later
            if (newKeyInput) {
                newKeyInput.value = "";
            }
        }
    }

    if (closeNewKeyModal) closeNewKeyModal.addEventListener("click", closeKeyModal);
    if (doneNewKeyBtn) doneNewKeyBtn.addEventListener("click", closeKeyModal);

    if (copyNewKeyBtn && newKeyInput) {
        if (copyNewKeyBtn) copyNewKeyBtn.addEventListener("click", () => {
            if (newKeyInput.value) {
                navigator.clipboard.writeText(newKeyInput.value).then(() => {
                    copyNewKeyBtn.textContent = "Copied!";
                    copyNewKeyBtn.style.background = "#059669";
                    setTimeout(() => {
                        copyNewKeyBtn.textContent = "Copy";
                        copyNewKeyBtn.style.background = "#10b981";
                    }, 2000);
                });
            }
        });
    }

    // Profile Dropdown Toggle
    if (navProfileTrigger && profileDropdown) {
        if (navProfileTrigger) navProfileTrigger.addEventListener("click", (e) => {
            e.stopPropagation();
            if (profileDropdown.style.display === "flex") {
                profileDropdown.style.display = "none";
            } else {
                profileDropdown.style.display = "flex";
            }
        });

        // Close dropdown when clicking outside
        document.addEventListener("click", (e) => {
            if (!profileContainer.contains(e.target)) {
                profileDropdown.style.display = "none";
            }
        });

        const closeProfileBtn = document.getElementById("close-profile-btn");
        if (closeProfileBtn) {
            if (closeProfileBtn) closeProfileBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                profileDropdown.style.display = "none";
            });
        }
    }

    // Landing Profile Dropdown Toggle
    if (landingProfileTrigger && landingProfileDropdown) {
        if (landingProfileTrigger) landingProfileTrigger.addEventListener("click", (e) => {
            e.stopPropagation();
            if (landingProfileDropdown.style.display === "flex") {
                landingProfileDropdown.style.display = "none";
            } else {
                landingProfileDropdown.style.display = "flex";
            }
        });

        // Close dropdown when clicking outside
        document.addEventListener("click", (e) => {
            if (landingProfileContainer && !landingProfileContainer.contains(e.target)) {
                landingProfileDropdown.style.display = "none";
            }
        });

        const landingCloseProfileBtn = document.getElementById("landing-close-profile-btn");
        if (landingCloseProfileBtn) {
            if (landingCloseProfileBtn) landingCloseProfileBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                landingProfileDropdown.style.display = "none";
            });
        }

    }

    const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "null");
    if (authData) {
        // Build a cached display key from stored key_prefix so the UI doesn't show "No API Key Generated"
        // when the /api/me call fails (e.g. due to expired Google JWT token)
        let cachedDisplayKey = null;
        if (authData.key_prefix) {
            cachedDisplayKey = authData.key_prefix + "••••••••••••••••••••••••••••••••";
        }
        showWelcomeScreen(authData.name, authData.email, authData.picture, authData.credential, cachedDisplayKey);
    }
});
