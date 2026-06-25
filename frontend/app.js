/* ==============================================================================
   DA-IICT Faculty AI Buddy - Frontend Login Logic (app.js)
   ============================================================================== */

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

    async function checkExistingKey(email) {
        try {
            const response = await fetch("/api/me", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: email })
            });
            if (response.ok) {
                const data = await response.json();
                if (data.has_key) {
                    const key = data.api_key;
                    apiKeyInput.value = key;
                    updateConfigSnippet(key);
                    if (userRoleBadge) {
                        userRoleBadge.textContent = "Role: " + (data.role || "User");
                    }
                    return true;
                }
            }
        } catch (e) {
            console.error("Error checking key", e);
        }
        return false;
    }

    async function generateKey(email, regenerate = false) {
        try {
            apiKeyInput.value = "Generating...";
            const endpoint = regenerate ? "/api/regenerate-key" : "/api/generate-key";
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: email })
            });
            if (response.ok) {
                const data = await response.json();
                const key = data.api_key;
                apiKeyInput.value = key;
                updateConfigSnippet(key);
                if (userRoleBadge) {
                    userRoleBadge.textContent = "Role: " + (data.role || "User");
                }
            } else {
                const err = await response.json();
                apiKeyInput.value = err.detail || "Error generating key.";
            }
        } catch (e) {
            console.error(e);
            apiKeyInput.value = "Error generating key.";
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

        // Claude Desktop (Stdio)
        const claudeText = `{
  "mcpServers": {
    "daiict": {
      "command": "cmd",
      "args": [
        "/c",
        "npx",
        "-y",
        "mcp-remote",
        "http://127.0.0.1:8001/mcp/sse",
        "--allow-http",
        "--transport",
        "sse-only",
        "--header",
        "Authorization:\\\${AUTH_HEADER}"
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
    "daiict": {
      "type": "sse",
      "url": "http://127.0.0.1:8001/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${key}"
      }
    }
  }
}`;
        if (cursorConfigCode) {
            cursorConfigCode.textContent = cursorText;
        }
    }

    let currentEmail = null;

    async function showWelcomeScreen(name, email, picture) {
        currentEmail = email;
        loginOverlay.style.display = "none";
        appContainer.style.display = "block"; // Use block layout for robust scrolling
        
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

        const hasKey = await checkExistingKey(email);
        if (!hasKey) {
            generateKey(email, false);
        }
    }

    // Check if user is already logged in
    const storedSession = localStorage.getItem("dau_buddy_auth");
    if (storedSession) {
        try {
            const authData = JSON.parse(storedSession);
            if (authData.email && (authData.email.endsWith("@dau.ac.in") || authData.email.endsWith("@daiict.ac.in"))) {
                // Valid session exists, bypass login
                showWelcomeScreen(authData.name, authData.email, authData.picture);
            }
        } catch (e) {
            console.error("Invalid auth session data", e);
            localStorage.removeItem("dau_buddy_auth");
        }
    }

    // Global callback for Google Sign-In
    window.handleCredentialResponse = (response) => {
        try {
            // Decode JWT token payload (middle part)
            const payloadBase64 = response.credential.split('.')[1];
            const decodedPayload = JSON.parse(atob(payloadBase64.replace(/-/g, '+').replace(/_/g, '/')));
            
            const email = decodedPayload.email;
            
            if (email && (email.endsWith("@dau.ac.in") || email.endsWith("@daiict.ac.in"))) {
                // Successful DAU login
                localStorage.setItem("dau_buddy_auth", JSON.stringify({ 
                    email: email, 
                    name: decodedPayload.name,
                    picture: decodedPayload.picture 
                }));
                loginError.style.display = "none";
                
                // Fade out overlay
                loginOverlay.style.opacity = "0";
                setTimeout(() => {
                    showWelcomeScreen(decodedPayload.name, email, decodedPayload.picture);
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
                        copyKeyBtn.style.background = "#3b82f6";
                    }, 2000);
                });
            }
        });
    }


    // Tab Switching functionality for Claude vs Cursor config
    const tabClaude = document.getElementById("tab-claude");
    const tabCursor = document.getElementById("tab-cursor");
    const contentClaude = document.getElementById("content-claude");
    const contentCursor = document.getElementById("content-cursor");

    if (tabClaude && tabCursor) {
        tabClaude.addEventListener("click", () => {
            tabClaude.style.background = "#3b82f6";
            tabClaude.style.color = "white";
            tabCursor.style.background = "transparent";
            tabCursor.style.color = "#a0a0a0";
            contentClaude.style.display = "block";
            contentCursor.style.display = "none";
        });
        tabCursor.addEventListener("click", () => {
            tabCursor.style.background = "#3b82f6";
            tabCursor.style.color = "white";
            tabClaude.style.background = "transparent";
            tabClaude.style.color = "#a0a0a0";
            contentClaude.style.display = "none";
            contentCursor.style.display = "block";
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
});
