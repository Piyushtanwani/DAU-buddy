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

document.addEventListener("DOMContentLoaded", () => {
    // ── Google OAuth & Session Management ─────────────────────────────────────
    const loginOverlay = document.getElementById("login-overlay");
    const appContainer = document.getElementById("app-container");
    const loginError = document.getElementById("login-error");
    const welcomeName = document.getElementById("welcome-name");
    const logoutBtn = document.getElementById("logout-btn");
    const apiKeyInput = document.getElementById("api-key-input");
    const copyKeyBtn = document.getElementById("copy-key-btn");
    const regenerateBtn = document.getElementById("regenerate-key-btn");
    const configCode = document.getElementById("claude-config-code");
    const cursorConfigCode = document.getElementById("cursor-config-code");
    const welcomeEmail = document.getElementById("welcome-email");
    const welcomeAvatar = document.getElementById("welcome-avatar");
    const userRoleBadge = document.getElementById("user-role-badge");

    async function checkExistingKey(credential) {
        // [Lines truncated for replace block; we will replace from the start of the file down to the old handleCredentialResponse]
        try {
            const response = await fetch("/api/me", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: credential })
            });
            if (response.ok) {
                const data = await response.json();

                // ALWAYS update the role if the API provides it
                if (userRoleBadge) {
                    const role = data.role || "User";
                    userRoleBadge.textContent = "Role: " + role;
                    const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                    authData.role = role;
                    localStorage.setItem("dau_buddy_auth", JSON.stringify(authData));
                }

                if (data.has_key) {
                    const key = data.api_key;
                    if (key) {
                        if (apiKeyInput.value === "Loading..." || apiKeyInput.value.includes("Please")) {
                            apiKeyInput.value = key;
                            updateConfigSnippet(key);
                        }
                        const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                        authData.api_key = key;
                        localStorage.setItem("dau_buddy_auth", JSON.stringify(authData));
                    }
                    return true;
                }
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
            apiKeyInput.value = "Generating...";
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
                apiKeyInput.value = key;
                const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                authData.api_key = key;
                localStorage.setItem("dau_buddy_auth", JSON.stringify(authData));

                const allKeys = JSON.parse(localStorage.getItem("dau_buddy_keys") || "{}");
                if (currentEmail) {
                    allKeys[currentEmail] = key;
                    localStorage.setItem("dau_buddy_keys", JSON.stringify(allKeys));
                }

                updateConfigSnippet(key);
                if (userRoleBadge) {
                    const role = data.role || "User";
                    userRoleBadge.textContent = "Role: " + role;

                    const updatedAuth = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                    updatedAuth.role = role;
                    localStorage.setItem("dau_buddy_auth", JSON.stringify(updatedAuth));
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
                apiKeyInput.value = errMsg;
                alert("API Error: " + errMsg);
            }
        } catch (e) {
            console.error(e);
            apiKeyInput.value = "Error generating key.";
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


    function updateConfigSnippet(key) {
        // Escape backslashes for JSON representation
        const escapedPythonPath = pythonPath.replace(/\\/g, "\\\\");
        const escapedProjectPath = projectPath.replace(/\\/g, "\\\\");
        const baseUrl = window.location.origin + "/mcp/sse";

        // Claude Desktop (Stdio)
        const claudeText = `{
  "mcpServers": {
    "DAU Buddy": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "${baseUrl}",
        "--allow-http",
        "--transport",
        "sse-only",
        "--header",
        "Authorization:${"${AUTH_HEADER}"}"
      ],
      "env": {
        "AUTH_HEADER": "Bearer ${key}"
      }
    }
  }
}`;
        configCode.textContent = claudeText;

        // Cursor / Windsurf (HTTP/SSE)
        const cursorText = `{
  "mcpServers": {
    "DAU Buddy": {
      "type": "sse",
      "url": "${baseUrl}",
      "headers": {
        "Authorization": "Bearer ${key}"
      }
    }
  }
}`;
        if (cursorConfigCode) {
            cursorConfigCode.textContent = cursorText;
        }

        // OpenCode (HTTP/SSE) - Uses "remote" type
        const opencodeText = `{
  "mcpServers": {
    "DAU Buddy": {
      "type": "remote",
      "url": "${baseUrl}",
      "headers": {
        "Authorization": "Bearer ${key}"
      }
    }
  }
}`;
        const opencodeConfigCode = document.getElementById("opencode-config-code");
        if (opencodeConfigCode) {
            opencodeConfigCode.textContent = opencodeText;
        }

        const connectorsApiKeyDisplay = document.getElementById("connectors-api-key-display");
        if (connectorsApiKeyDisplay) {
            connectorsApiKeyDisplay.textContent = key;
        }

        const connectorsUrlDisplay = document.getElementById("connectors-url-display");
        if (connectorsUrlDisplay) {
            connectorsUrlDisplay.textContent = baseUrl;
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

            loginOverlay.style.opacity = "0";
            loginOverlay.style.display = "none";
            appContainer.style.display = "block";
            sessionStorage.setItem("dau_buddy_view", "dashboard");
        }

        welcomeName.textContent = name || "User"; // Use block layout for robust scrolling

        if (name) {
            // If the display name is purely numeric (e.g. "2025 12063"), use the email local part instead
            const firstName = name.split(" ")[0];
            const displayName = /^\d+$/.test(firstName) ? email.split("@")[0] : firstName;
            welcomeName.textContent = `Welcome, ${displayName}!`;
        }
        welcomeEmail.textContent = email;

        if (picture) {
            welcomeAvatar.src = picture;
            welcomeAvatar.style.display = "block";
            document.getElementById("welcome-icon").style.display = "none";
        }

        // Determine role synchronously from email
        if (userRoleBadge && email) {
            let role = "User";
            if (email.endsWith("@dau.ac.in")) {
                const localPart = email.split("@")[0];
                if (/^\d+$/.test(localPart)) {
                    role = "Student";
                } else {
                    role = "Faculty/Staff";
                }
            }
            userRoleBadge.textContent = "Role: " + role;
        }

        // Try to recover key from persistent key storage if not in session cache
        let activeKey = cachedKey;
        if (!activeKey) {
            const allKeys = JSON.parse(localStorage.getItem("dau_buddy_keys") || "{}");
            if (allKeys[currentEmail]) {
                activeKey = allKeys[currentEmail];
                // Restore to session
                const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
                authData.api_key = activeKey;
                localStorage.setItem("dau_buddy_auth", JSON.stringify(authData));
            }
        }

        // Only use activeKey if it's an actual hex key
        if (activeKey && activeKey !== "Loading..." && activeKey !== "No API Key Generated" && activeKey !== "No key exists. Please generate.") {
            apiKeyInput.value = activeKey;
            updateConfigSnippet(activeKey);
            if (regenerateBtn) regenerateBtn.textContent = "Regenerate Key";

            // Restore role if saved
            const authData = JSON.parse(localStorage.getItem("dau_buddy_auth") || "{}");
            if (authData.role && userRoleBadge) {
                userRoleBadge.textContent = "Role: " + authData.role;
            }

            // Sync status/role in background if we have credential
            if (currentCredential) {
                checkExistingKey(currentCredential);
            }
        } else if (currentCredential) {
            const hasKey = await checkExistingKey(currentCredential);
            if (!hasKey) {
                apiKeyInput.value = "No API Key Generated";
                if (regenerateBtn) regenerateBtn.textContent = "Generate Key";
                updateConfigSnippet("YOUR_API_KEY_HERE");
            } else {
                if (regenerateBtn) {
                    regenerateBtn.textContent = "Generate Key";
                }
                apiKeyInput.value = "No key exists. Please generate.";
                updateConfigSnippet("YOUR_API_KEY_HERE");
            }
        } else {
            // Should not happen, but fallback
            apiKeyInput.value = "Please Login Again";
            if (userRoleBadge) userRoleBadge.textContent = "";
        }

        if (regenerateBtn) {
            regenerateBtn.onclick = async () => {
                const isRegenerating = regenerateBtn.textContent.includes("Regenerate") || regenerateBtn.textContent.includes("Generating");
                await generateKey(currentCredential, isRegenerating);
            };
        }
    }
    // Handle URL parameters for view routing from external pages (like docs.html)
    const urlParams = new URLSearchParams(window.location.search);
    const viewParam = urlParams.get('view');
    if (viewParam === 'landing' || viewParam === 'dashboard') {
        sessionStorage.setItem("dau_buddy_view", viewParam);
        // Clean up the URL so refresh works normally
        window.history.replaceState({}, document.title, window.location.pathname);
    } else if (viewParam === 'login') {
        sessionStorage.setItem("dau_buddy_view", "landing");
        window.history.replaceState({}, document.title, window.location.pathname);
        // Wait just a tiny bit for the UI to be ready
        setTimeout(() => {
            const loginOverlay = document.getElementById("login-overlay");
            if (loginOverlay) {
                loginOverlay.style.display = "flex";
                setTimeout(() => loginOverlay.style.opacity = "1", 10);
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
                const currentView = sessionStorage.getItem("dau_buddy_view");
                const shouldShowDashboard = (currentView === "dashboard");

                // Valid session exists, configure UI
                showWelcomeScreen(authData.name, authData.email, authData.picture, authData.credential, authData.api_key, shouldShowDashboard);
                
                // Update landing page buttons to indicate they lead to the dashboard
                const btnSignIn = document.getElementById("nav-signin-btn");
                const btnGetStarted = document.getElementById("hero-get-started-btn");
                if (btnSignIn) btnSignIn.textContent = "Dashboard";
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
                if (btnSignIn) btnSignIn.textContent = "Dashboard";
                if (btnGetStarted) btnGetStarted.textContent = "Go to Dashboard";

                // Fade out overlay
                loginOverlay.style.opacity = "0";
                setTimeout(() => {
                    loginOverlay.style.display = "none";
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
    if (logoutBtn) {
        logoutBtn.addEventListener("click", () => {
            localStorage.removeItem("dau_buddy_auth");
            sessionStorage.removeItem("dau_buddy_view");
            appContainer.style.display = "none";

            const landingView = document.getElementById("landing-view");
            if (landingView) landingView.style.display = "block";

            // Revert landing page buttons back to original text
            const btnSignIn = document.getElementById("nav-signin-btn");
            const btnGetStarted = document.getElementById("hero-get-started-btn");
            if (btnSignIn) btnSignIn.textContent = "Sign In";
            if (btnGetStarted) btnGetStarted.textContent = "Access MCP Server";

            loginOverlay.style.opacity = "1";
            loginOverlay.style.display = "flex";
        });
    }

    // Copy Button functionality
    if (copyKeyBtn) {
        copyKeyBtn.addEventListener("click", () => {
            const key = apiKeyInput.value;
            if (key && !key.includes("Please") && !key.includes("Loading")) {
                navigator.clipboard.writeText(key).then(() => {
                    copyKeyBtn.textContent = "Copied!";
                    copyKeyBtn.style.background = "#10b981";
                    setTimeout(() => {
                        copyKeyBtn.textContent = "Copy";
                        copyKeyBtn.style.background = "#0f3b73";
                    }, 2000);
                });
            }
        });
    }

    // Landing Page UI functionality
    const btnGetStarted = document.getElementById("hero-get-started-btn");
    const btnSignIn = document.getElementById("nav-signin-btn");
    const btnCloseLogin = document.getElementById("close-login-btn");
    const homeBtn = document.getElementById("home-btn");

    if (homeBtn) {
        homeBtn.addEventListener("click", () => {
            appContainer.style.display = "none";
            const landingView = document.getElementById("landing-view");
            if (landingView) landingView.style.display = "block";
            sessionStorage.setItem("dau_buddy_view", "landing");
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
                    appContainer.style.display = "block";
                    sessionStorage.setItem("dau_buddy_view", "dashboard");
                    return;
                }
            } catch (e) {}
        }

        loginOverlay.style.display = "flex";
        setTimeout(() => loginOverlay.style.opacity = "1", 10);
    }

    function closeLoginModal() {
        loginOverlay.style.opacity = "0";
        setTimeout(() => loginOverlay.style.display = "none", 300);
    }

    if (btnGetStarted) btnGetStarted.addEventListener("click", openLoginModal);
    if (btnSignIn) btnSignIn.addEventListener("click", openLoginModal);
    if (btnCloseLogin) btnCloseLogin.addEventListener("click", closeLoginModal);


    // Tab Switching functionality
    const tabClaude = document.getElementById("tab-claude");
    const tabCursor = document.getElementById("tab-cursor");
    const tabOpenCode = document.getElementById("tab-opencode");
    const tabConnectors = document.getElementById("tab-connectors");

    const contentClaude = document.getElementById("content-claude");
    const contentCursor = document.getElementById("content-cursor");
    const contentOpenCode = document.getElementById("content-opencode");
    const contentConnectors = document.getElementById("content-connectors");

    function resetTabs() {
        [tabClaude, tabCursor, tabOpenCode, tabConnectors].forEach(tab => {
            if (tab) {
                tab.style.background = "transparent";
                tab.style.color = "#a0a0a0";
            }
        });
        [contentClaude, contentCursor, contentOpenCode, contentConnectors].forEach(content => {
            if (content) content.style.display = "none";
        });
    }

    if (tabClaude) {
        tabClaude.addEventListener("click", () => {
            resetTabs();
            tabClaude.style.background = "#0f3b73";
            tabClaude.style.color = "white";
            contentClaude.style.display = "block";
        });
    }

    if (tabCursor) {
        tabCursor.addEventListener("click", () => {
            resetTabs();
            tabCursor.style.background = "#0f3b73";
            tabCursor.style.color = "white";
            contentCursor.style.display = "block";
        });
    }

    if (tabOpenCode) {
        tabOpenCode.addEventListener("click", () => {
            resetTabs();
            tabOpenCode.style.background = "#0f3b73";
            tabOpenCode.style.color = "white";
            contentOpenCode.style.display = "block";
        });
    }

    if (tabConnectors) {
        tabConnectors.addEventListener("click", () => {
            resetTabs();
            tabConnectors.style.background = "#0f3b73";
            tabConnectors.style.color = "white";
            contentConnectors.style.display = "block";
        });
    }

    // Config Copy Buttons
    const copyClaudeBtn = document.getElementById("copy-claude-btn");
    if (copyClaudeBtn) {
        copyClaudeBtn.addEventListener("click", () => {
            navigator.clipboard.writeText(configCode.textContent).then(() => {
                copyClaudeBtn.textContent = "Copied!";
                copyClaudeBtn.style.background = "#10b981";
                copyClaudeBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyClaudeBtn.textContent = "Copy";
                    copyClaudeBtn.style.background = "rgba(255,255,255,0.1)";
                    copyClaudeBtn.style.borderColor = "#444";
                }, 2000);
            });
        });
    }

    const copyCursorBtn = document.getElementById("copy-cursor-btn");
    if (copyCursorBtn && cursorConfigCode) {
        copyCursorBtn.addEventListener("click", () => {
            navigator.clipboard.writeText(cursorConfigCode.textContent).then(() => {
                copyCursorBtn.textContent = "Copied!";
                copyCursorBtn.style.background = "#10b981";
                copyCursorBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyCursorBtn.textContent = "Copy";
                    copyCursorBtn.style.background = "rgba(255,255,255,0.1)";
                    copyCursorBtn.style.borderColor = "#444";
                }, 2000);
            });
        });
    }

    const copyOpenCodeBtn = document.getElementById("copy-opencode-btn");
    const opencodeConfigCode = document.getElementById("opencode-config-code");
    if (copyOpenCodeBtn && opencodeConfigCode) {
        copyOpenCodeBtn.addEventListener("click", () => {
            navigator.clipboard.writeText(opencodeConfigCode.textContent).then(() => {
                copyOpenCodeBtn.textContent = "Copied!";
                copyOpenCodeBtn.style.background = "#10b981";
                copyOpenCodeBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyOpenCodeBtn.textContent = "Copy";
                    copyOpenCodeBtn.style.background = "rgba(255,255,255,0.1)";
                    copyOpenCodeBtn.style.borderColor = "#444";
                }, 2000);
            });
        });
    }

    const copyConnNameBtn = document.getElementById("copy-conn-name");
    if (copyConnNameBtn) {
        copyConnNameBtn.addEventListener("click", () => {
            navigator.clipboard.writeText("DAU Buddy").then(() => {
                copyConnNameBtn.textContent = "Copied!";
                copyConnNameBtn.style.background = "#10b981";
                copyConnNameBtn.style.color = "white";
                copyConnNameBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyConnNameBtn.textContent = "Copy";
                    copyConnNameBtn.style.background = "#f0f0f0";
                    copyConnNameBtn.style.color = "#333";
                    copyConnNameBtn.style.borderColor = "#ccc";
                }, 2000);
            });
        });
    }

    const copyConnUrlBtn = document.getElementById("copy-conn-url");
    const connectorsUrlDisplay = document.getElementById("connectors-url-display");
    if (copyConnUrlBtn && connectorsUrlDisplay) {
        copyConnUrlBtn.addEventListener("click", () => {
            const urlToCopy = connectorsUrlDisplay.textContent;
            navigator.clipboard.writeText(urlToCopy).then(() => {
                copyConnUrlBtn.textContent = "Copied!";
                copyConnUrlBtn.style.background = "#10b981";
                copyConnUrlBtn.style.color = "white";
                copyConnUrlBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyConnUrlBtn.textContent = "Copy";
                    copyConnUrlBtn.style.background = "#f0f0f0";
                    copyConnUrlBtn.style.color = "#333";
                    copyConnUrlBtn.style.borderColor = "#ccc";
                }, 2000);
            });
        });
    }

    const copyConnKeyBtn = document.getElementById("copy-conn-key");
    const connApiKeyDisplay = document.getElementById("connectors-api-key-display");
    if (copyConnKeyBtn && connApiKeyDisplay) {
        copyConnKeyBtn.addEventListener("click", () => {
            const keyToCopy = connApiKeyDisplay.textContent;
            navigator.clipboard.writeText(keyToCopy).then(() => {
                copyConnKeyBtn.textContent = "Copied!";
                copyConnKeyBtn.style.background = "#10b981";
                copyConnKeyBtn.style.color = "white";
                copyConnKeyBtn.style.borderColor = "#10b981";
                setTimeout(() => {
                    copyConnKeyBtn.textContent = "Copy";
                    copyConnKeyBtn.style.background = "#f0f0f0";
                    copyConnKeyBtn.style.color = "#333";
                    copyConnKeyBtn.style.borderColor = "#ccc";
                }, 2000);
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
        feedbackBtn.addEventListener("click", () => {
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

        closeFeedbackBtn.addEventListener("click", closeModal);
        cancelFeedbackBtn.addEventListener("click", closeModal);
        feedbackModal.addEventListener("click", (e) => {
            if (e.target === feedbackModal) closeModal();
        });

        if (feedbackDesc && charCount) {
            feedbackDesc.addEventListener("input", (e) => {
                const len = e.target.value.length;
                charCount.textContent = len;
                if (len >= 1000) {
                    charCount.parentElement.classList.add("limit-reached");
                } else {
                    charCount.parentElement.classList.remove("limit-reached");
                }
            });
        }

        if (feedbackForm) {
            feedbackForm.addEventListener("submit", async (e) => {
                e.preventDefault();
                const category = document.getElementById("feedback-category").value;
                const subject = document.getElementById("feedback-subject").value.trim();
                const description = feedbackDesc.value.trim();

                if (!category || !subject || !description) {
                    showToast("Please fill in all required fields.", "error");
                    return;
                }

                // Get current API key
                const currentKey = apiKeyInput ? apiKeyInput.value : null;
                if (!currentKey || currentKey === "Loading..." || currentKey.includes("Please")) {
                    showToast("API Key not found. Please log in again.", "error");
                    return;
                }

                submitFeedbackBtn.disabled = true;
                if (submitText) submitText.style.display = "none";
                if (loader) loader.style.display = "block";

                try {
                    const response = await fetch("/api/feedback", {
                        method: "POST",
                        headers: { 
                            "Content-Type": "application/json",
                            "Authorization": `Bearer ${currentKey}`
                        },
                        body: JSON.stringify({ category, subject, description })
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
                    submitFeedbackBtn.disabled = false;
                    if (submitText) submitText.style.display = "block";
                    if (loader) loader.style.display = "none";
                }
            });
        }
    }
});
