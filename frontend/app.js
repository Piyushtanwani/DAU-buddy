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
                const err = await response.json();
                apiKeyInput.value = (typeof err.detail === 'object') ? JSON.stringify(err.detail) : (err.detail || "Error generating key.");
            }
        } catch (e) {
            console.error(e);
            apiKeyInput.value = "Error generating key.";
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
      "command": "cmd",
      "args": [
        "/c",
        "npx",
        "-y",
        "mcp-remote",
        "${baseUrl}",
        "--allow-http",
        "--transport",
        "sse-only",
        "--header",
        "Authorization:${AUTH_HEADER}"
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

        // OpenCode (HTTP/SSE) - Assumed identical to Cursor for now
        const opencodeConfigCode = document.getElementById("opencode-config-code");
        if (opencodeConfigCode) {
            opencodeConfigCode.textContent = cursorText;
        }

        const connectorsApiKeyDisplay = document.getElementById("connectors-api-key-display");
        if (connectorsApiKeyDisplay) {
            connectorsApiKeyDisplay.textContent = key;
        }
    }

    let currentCredential = null;
    let currentEmail = null;

    async function showWelcomeScreen(name, email, picture, credential = null, cachedKey = null) {
        currentEmail = email;
        if (credential) currentCredential = credential;

        // Hide landing page and login overlay
        const landingView = document.getElementById("landing-view");
        if (landingView) landingView.style.display = "none";

        loginOverlay.style.opacity = "0";
        loginOverlay.style.display = "none";
        appContainer.style.display = "block";

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

    // Check if user is already logged in
    const storedSession = localStorage.getItem("dau_buddy_auth");
    if (storedSession) {
        try {
            const authData = JSON.parse(storedSession);
            if (authData.email && authData.credential) {
                // Valid session exists, bypass login
                showWelcomeScreen(authData.name, authData.email, authData.picture, authData.credential, authData.api_key);
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
            appContainer.style.display = "none";

            const landingView = document.getElementById("landing-view");
            if (landingView) landingView.style.display = "block";

            loginOverlay.style.opacity = "1";
            loginOverlay.style.display = "flex";
        });
    }

    // Copy Button functionality
    if (copyKeyBtn) {
        copyKeyBtn.addEventListener("click", () => {
            const key = apiKeyInput.value;
            if (key && key !== "Generating..." && key !== "Error generating key.") {
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

    function openLoginModal() {
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
    if (copyConnUrlBtn) {
        copyConnUrlBtn.addEventListener("click", () => {
            navigator.clipboard.writeText("https://dau-buddy.onrender.com/mcp/sse").then(() => {
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
});
