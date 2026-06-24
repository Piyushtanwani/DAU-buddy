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
    const welcomeEmail = document.getElementById("welcome-email");
    const welcomeAvatar = document.getElementById("welcome-avatar");

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
                    apiKeyInput.value = "dau_sk_•••••••••••••••• (Hidden for security)";
                    updateConfigSnippet("dau_sk_xxxxx");
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
            } else {
                const err = await response.json();
                apiKeyInput.value = err.detail || "Error generating key.";
            }
        } catch (e) {
            console.error(e);
            apiKeyInput.value = "Error generating key.";
        }
    }

    function updateConfigSnippet(key) {
        const configText = `{
  "mcpServers": {
    "daiict": {
      "url": "http://localhost:8001/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${key}"
      }
    }
  }
}`;
        configCode.textContent = configText;
    }

    let currentEmail = null;

    async function showWelcomeScreen(name, email, picture) {
        currentEmail = email;
        loginOverlay.style.display = "none";
        appContainer.style.display = "block"; // Use block layout for robust scrolling
        
        if (name) {
            welcomeName.textContent = `Welcome, ${name.split(" ")[0]}!`;
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

    // Regenerate Button functionality
    if (regenerateBtn) {
        regenerateBtn.addEventListener("click", () => {
            if (currentEmail && confirm("Are you sure you want to regenerate your API key? This will instantly revoke your current key and break any existing Claude Desktop connections.")) {
                generateKey(currentEmail, true);
            }
        });
    }
});
